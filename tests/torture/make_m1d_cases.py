"""M1d torture cases (docs/plans/2026-10-29-m1d-checks-cli.md, Task 1). Writes main.k always; writes expected.toml
once VERDICT holds LS-DYNA's answer for the case. Run: .venv/Scripts/python tests/torture/make_m1d_cases.py"""
import json
from pathlib import Path

HERE = Path(__file__).parent


def i10(*vals):
    return "".join(f"{v:>10}" for v in vals)


def i20(*vals):
    return "".join(f"{v:>20}" for v in vals)


BASE = "\n".join([
    "*KEYWORD", "*TITLE", "deckcheck torture: {title}", "*CONTROL_TERMINATION", "    1.0E-6",
    "*PART", "plate", i10(1, 1, 1),
    "*SECTION_SHELL", i10(1, 2), i10(1.0, 1.0, 1.0, 1.0),
    "*MAT_ELASTIC", i10(1, "7.85E-9", "210000.0", 0.3),
    "*NODE", "       1             0.0             0.0             0.0", "       2            10.0             0.0             0.0",
    "       3            10.0            10.0             0.0", "       4             0.0            10.0             0.0",
    "*ELEMENT_SHELL", "       1       1       1       2       3       4",
    "*DEFINE_CURVE", i10(1), i20(0.0, 1.0), i20(1.0, 1.0),
    "*SET_NODE_LIST", i10(1), i10(1, 2),
]) + "\n{extra}*END\n"

# name -> (title, extra text from line 28, the probed (kind, id, line, columns) or None)
CASES = {
    "m1d_base": ("base model for M1d cases", "", None),
    "m1d_bpm_set_none": ("prescribed motion names a missing node set",
                         "*BOUNDARY_PRESCRIBED_MOTION_SET\n" + i10(99, 3, 0, 1, 1.0) + "\n", ("SET_NODE", 99, 29, [8, 10])),
    "m1d_load_node_set_none": ("nodal load names a missing node set",
                               "*LOAD_NODE_SET\n" + i10(99, 3, 1, 1.0) + "\n", ("SET_NODE", 99, 29, [8, 10])),
    "m1d_load_segment_set_none": ("pressure load names a missing segment set",
                                  "*LOAD_SEGMENT_SET\n" + i10(99, 1, 1.0) + "\n", ("SET_SEGMENT", 99, 29, [8, 10])),
    "m1d_initial_velocity_none": ("initial velocity names a missing node set",
                                  "*INITIAL_VELOCITY\n" + i10(99) + "\n" + i10(0.0, 0.0, 1.0) + "\n",
                                  ("SET_NODE", 99, 29, [8, 10])),
    "m1d_history_node_set_none": ("history output names a missing node set",
                                  "*DATABASE_HISTORY_NODE_SET\n" + i10(99) + "\n", ("SET_NODE", 99, 29, [8, 10])),
    "m1d_dup_part": ("part 1 defined twice", "*PART\nplate again\n" + i10(1, 1, 1) + "\n", ("PART", 1, 30, [9, 10])),
    "m1d_dup_mat": ("material 1 defined twice, second with E = 70000",
                    "*MAT_ELASTIC\n" + i10(1, "7.85E-9", "70000.0", 0.3) + "\n", ("MAT", 1, 29, [9, 10])),
    "m1d_dup_section": ("section 1 defined twice, second 2.0 thick",
                        "*SECTION_SHELL\n" + i10(1, 2) + "\n" + i10(2.0, 2.0, 2.0, 2.0) + "\n", ("SECTION", 1, 29, [9, 10])),
    "m1d_dup_curve": ("curve 1 defined twice",
                      "*DEFINE_CURVE\n" + i10(1) + "\n" + i20(0.0, 2.0) + "\n" + i20(1.0, 2.0) + "\n",
                      ("DEFINE_CURVE", 1, 29, [9, 10])),
    "m1d_dup_node_set": ("node set 1 defined twice", "*SET_NODE_LIST\n" + i10(1) + "\n" + i10(3, 4) + "\n",
                         ("SET_NODE", 1, 29, [9, 10])),
    "m1d_dup_node": ("node 1 defined twice",
                     "*NODE\n       1             0.0             0.0             5.0\n", ("NODE", 1, 29, [7, 8])),
    "m1d_dup_node_same": ("node 1 defined twice at the same coordinates",
                          "*NODE\n       1             0.0             0.0             0.0\n", ("NODE", 1, 29, [7, 8])),
    "m1d_overflow_node": ("a 9-digit node id spills into the 8-wide id field's neighbour",
                          "*NODE\n123456789             5.0             5.0             0.0\n", None),
    "m1d_mixed_free": ("two values in one comma-separated slot",
                       "*MAT_ELASTIC\n" + "         2,7.85E-9,  210000.0       0.3" + "\n*PART\nplate 2\n"
                       + i10(2, 1, 2) + "\n*ELEMENT_SHELL\n       2       2       1       2       3       4\n", None),
    "m1d_umat": ("user-defined material (umat41) on a second part",
                 "*PART\nuser material\n" + i10(2, 1, 2) + "\n*MAT_USER_DEFINED_MATERIAL_MODELS\n"
                 + i10(2, "7.85E-9", 41, 4, 0, 0, 3, 4) + "\n" + i10(0, 0, 0, 0, 0, 0) + "\n"
                 + i10("210000.0", 0.3, "175000.0", "80769.2") + "\n", None),
}

# Filled in Step 4 from bakeoff/results/m1d_referee.txt: name -> (lsdyna_valid, note quoting the deciding line)
VERDICT: dict[str, tuple[bool, str]] = {
    "m1d_base": (True, "LS-DYNA R16.1 Student 2026-10-29: accepted, no warning"),
    "m1d_bpm_set_none": (False, "Error 10144: node set for imposed boundary # 99 is not found"),
    "m1d_load_node_set_none": (False, "Error 10144: node set for point load # 99 is not found"),
    "m1d_load_segment_set_none": (False, "Error 10144: segment set for pressure load # 99 is not found"),
    "m1d_initial_velocity_none": (False, "Error 10144: node set for initial velocities # 99 is not found"),
    "m1d_history_node_set_none": (False, "Error 10144: node set for node time history # 99 is not found"),
    "m1d_dup_part": (False, "Error 10176: repeated part ID 1"),
    "m1d_dup_mat": (False, "Error 10137: Multiply defined MATERIAL ID MATERIAL 1 at 2th input"),
    "m1d_dup_section": (False, "Error 10137: Multiply defined SECTION ID SECTION 1 at 2th input"),
    "m1d_dup_curve": (False, "Error 10173: repeated load curve/table id 1 in *DEFINE_CURVE"),
    "m1d_dup_node_set": (False, "Error 10110/10111: *SET_NODE id has 1 total duplications"),
    "m1d_dup_node": (False, "Error 11168: Duplicate node ID 1 with non-matching coordinates"),
    "m1d_dup_node_same": (True, "accepted, no warning: a duplicate node at identical coordinates (compare m1d_dup_node, Error 11168)"),
    "m1d_overflow_node": (True, "accepted, no warning, but misread: d3hsp echoes node 12345678 at x = 95.0 (deck: "
                                "id 123456789, x 5.0). A silent misread deckcheck does not detect in M1 (M4)."),
    "m1d_mixed_free": (True, "accepted and read correctly: d3hsp echoes material 2 with e = 2.1E+05, vnu = 0.3"),
    "m1d_umat": (True, "accepted, no warning (umat41 built in)"),
}


def expected(name: str, probe, valid: bool, note: str) -> str:
    lines = [f"lsdyna_valid = {'true' if valid else 'false'}", "findings = []", f"note = {json.dumps(note)}"]
    if probe and name.startswith("m1d_dup_"):
        kind, id_, line, cols = probe
        lines += ["", "[index]", f'duplicates = [{{kind = "{kind}", id = {id_}, file = "main.k", line = {line}, '
                  f"columns = [{cols[0]}, {cols[1]}]}}]"]
    elif probe and not valid:  # rejected: the missing set is a dangling reference (DC001)
        kind, id_, line, cols = probe
        lines += ["", "[index]", f'dangling = [{{kind = "{kind}", id = {id_}, file = "main.k", line = {line}, '
                  f"columns = [{cols[0]}, {cols[1]}]}}]"]
    elif probe:  # accepted with the set missing: LS-DYNA doesn't check it (DC006, Task 3)
        kind, id_, line, cols = probe
        lines += ["", "[[diagnostics]]", 'code = "DC006"', 'severity = "warning"', 'file = "main.k"',
                  f"line = {line}", f"columns = [{cols[0]}, {cols[1]}]"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    for name, (title, extra, probe) in CASES.items():
        folder = HERE / name
        folder.mkdir(exist_ok=True)
        (folder / "main.k").write_bytes(BASE.format(title=title, extra=extra).encode("latin-1"))
        if name in VERDICT:
            (folder / "expected.toml").write_text(expected(name, probe, *VERDICT[name]), encoding="utf-8")
