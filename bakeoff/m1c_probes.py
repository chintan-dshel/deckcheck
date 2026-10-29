"""Ask LS-DYNA (a) which *INCLUDE_TRANSFORM offset field applies to which entity kind, and (b) whether an absolute
include name is read. Probe decks are built in temporary folders, never committed (M1c plan, Task 1).

(a) One entity of the kind, id 1, sits in sub.k. Every offset field gets a distinct value, and the main deck
references the entity as 1 + one candidate field's offset. A control run (all offsets 0, reference 1) must pass
first, and a negative control (reference 1 + NO_FIELD) must fail. Kinds whose probe needs another kind's offset run
after it."""
import json
import sys
import tempfile
from pathlib import Path

from bakeoff.lsdyna_oracle import lsdyna_reads

FIELDS = ["idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff", "iddoff", "idroff"]
DISTINCT = {f: 100 * (i + 1) for i, f in enumerate(FIELDS)}
ZERO = {f: 0 for f in FIELDS}
NO_FIELD = 999
OUT = Path("bakeoff/results/m1c_probes.json")


def i10(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals)


def transform(off: dict[str, int]) -> str:
    return ("*INCLUDE_TRANSFORM\nsub.k\n" + i10(*(off[f] for f in FIELDS[:7])) + "\n" + i10(off["idroff"])
            + "\n\n\n")


def nodes(first: int) -> str:
    xy = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    return "*NODE\n" + "".join(f"{first + k:>8}{x:>16}{y:>16}{0.0:>16}\n" for k, (x, y) in enumerate(xy))


def model(pid=1, sec=1, mat=1, hg=0, n0=0, part_id=1, sec_id=1, mat_id=1, skip=()) -> str:
    """A one-element model; ids that point elsewhere are parameters, and `skip` drops kinds that live in sub.k."""
    out = ""
    if "PART" not in skip:
        out += "*PART\nplate\n" + i10(part_id, sec, mat, 0, hg) + "\n"
    if "SECTION" not in skip:
        out += "*SECTION_SHELL\n" + i10(sec_id, 2) + "\n" + i10(1.0, 1.0, 1.0, 1.0) + "\n"
    if "MAT" not in skip:
        out += "*MAT_ELASTIC\n" + i10(mat_id, "7.85E-9", "210000.0", 0.3) + "\n"
    if "NODE" not in skip:
        out += nodes(n0 + 1)
    out += "*ELEMENT_SHELL\n" + "".join(f"{v:>8}" for v in (1, pid, n0 + 1, n0 + 2, n0 + 3, n0 + 4)) + "\n"
    return out


def probe(kind: str, ref: int, known: dict[str, int]) -> tuple[str, str]:
    """(main body, sub.k body) asking whether the main deck's reference `ref` reaches the entity in sub.k."""
    if kind == "MAT":
        return model(mat=ref, skip=("MAT",)), "*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n"
    if kind == "SECTION":
        return model(sec=ref, skip=("SECTION",)), "*SECTION_SHELL\n" + i10(1, 2) + "\n" + i10(1.0, 1.0, 1.0, 1.0) + "\n"
    if kind == "HOURGLASS":
        return model(hg=ref), "*HOURGLASS\n" + i10(1, 1) + "\n"
    if kind == "NODE":
        return model(n0=ref - 1, skip=("NODE",)), nodes(1)
    if kind == "DEFINE_CURVE":
        return (model() + "*LOAD_NODE_POINT\n" + i10(1, 3, ref, 1.0) + "\n",
                "*DEFINE_CURVE\n" + i10(1) + "\n" + f"{0.0:>20}{1.0:>20}\n{1.0:>20}{1.0:>20}\n")
    if kind == "PART":  # sub.k's part points at section 1 and material 1, shifted by their own offsets
        return (model(pid=ref, sec_id=1 + known["SECTION"], mat_id=1 + known["MAT"], skip=("PART",)),
                "*PART\nplate\n" + i10(1, 1, 1) + "\n")
    if kind == "SET_PART":  # sub.k's set lists part 1, shifted by the part offset
        p = 1 + known["PART"]
        return (model(pid=p, part_id=p) + "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(ref, 0, 2, 0) + "\n"
                + i10(0.0, 0.0) + "\n" + i10(1.0, 1.0) + "\n", "*SET_PART_LIST\n" + i10(1) + "\n" + i10(1) + "\n")
    if kind == "SET_NODE":  # sub.k's set lists nodes 1 and 2, shifted by the node offset. A nodes-to-surface
        n0 = known["NODE"]  # contact checks its node set (contact_type4_bad); *BOUNDARY_SPC_SET does not (spc_set_none)
        return (model(n0=n0) + "*CONTACT_NODES_TO_SURFACE\n" + i10(ref, 1, 4, 3) + "\n"
                + i10(0.0, 0.0) + "\n" + i10(1.0, 1.0) + "\n", "*SET_NODE_LIST\n" + i10(1) + "\n" + i10(1, 2) + "\n")
    if kind == "ELEMENT_SHELL":  # the whole model sits in sub.k, so its ids shift together (M1c Task 7, Yaris wall)
        return "*DATABASE_HISTORY_SHELL\n" + i10(ref) + "\n", model()
    if kind == "SET_SEGMENT":  # a segment set over the model's shell, all in sub.k; a contact in main.k names it
        return ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(ref, 0, 0, 0) + "\n" + i10(0.0, 0.0) + "\n"
                + i10(1.0, 1.0) + "\n", model() + "*SET_SEGMENT\n" + i10(1) + "\n" + i10(1, 2, 3, 4) + "\n")
    raise ValueError(kind)


NEEDS = {"PART": ("SECTION", "MAT"), "SET_PART": ("PART",), "SET_NODE": ("NODE",)}
ORDER = ["MAT", "SECTION", "HOURGLASS", "NODE", "DEFINE_CURVE", "PART", "SET_PART", "SET_NODE"]


def run(main_body: str, sub: str, off: dict[str, int]) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp)
        head = "*KEYWORD\n*TITLE\ndeckcheck offset probe\n*CONTROL_TERMINATION\n    1.0E-6\n"
        (case / "main.k").write_bytes((head + transform(off) + main_body + "*END\n").encode("latin-1"))
        (case / "sub.k").write_bytes(("*KEYWORD\n" + sub + "*END\n").encode("latin-1"))
        return lsdyna_reads(case)[0]


def offsets(kinds=ORDER) -> dict:
    out, known = {}, {}
    for kind in kinds:
        if any(k not in known for k in NEEDS.get(kind, ())):
            out[kind] = {"control": None, "accepted": [], "decided": None, "skipped": "a needed kind is undecided"}
            continue
        # the control shifts nothing, so a needed kind's offset is 0 there too
        control = run(*probe(kind, 1, {k: 0 for k in known}), ZERO)
        shifted = {k: DISTINCT[f] for k, f in known.items()}
        # the negative control names an id no offset produces; LS-DYNA must reject it or the probe can't tell fields apart
        negative = control and run(*probe(kind, 1 + NO_FIELD, shifted), DISTINCT)
        accepted = [f for f in FIELDS if control and run(*probe(kind, 1 + DISTINCT[f], shifted), DISTINCT)]
        decided = accepted[0] if control and not negative and len(accepted) == 1 else None
        if decided:
            known[kind] = decided
        out[kind] = {"control": control, "negative": negative, "accepted": accepted, "decided": decided}
        print(kind, out[kind], flush=True)
    return out


def absolute_include() -> bool:
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as lib:
        mat = Path(lib) / "mat.k"
        mat.write_bytes(("*KEYWORD\n*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n*END\n").encode("latin-1"))
        head = "*KEYWORD\n*TITLE\ndeckcheck absolute include\n*CONTROL_TERMINATION\n    1.0E-6\n"
        (Path(tmp) / "main.k").write_bytes((head + f"*INCLUDE\n{mat}\n" + model(skip=("MAT",)) + "*END\n")
                                           .encode("latin-1"))
        return lsdyna_reads(Path(tmp))[0]


if __name__ == "__main__":
    if len(sys.argv) > 1:  # probe the named self-contained kinds only and add them to the results file
        results = json.loads(OUT.read_text(encoding="utf-8"))
        results["offsets"].update(offsets(sys.argv[1:]))
    else:
        results = {"offsets": offsets(), "inc_absolute": absolute_include()}
    OUT.write_text(json.dumps(results, indent=1), encoding="utf-8")
