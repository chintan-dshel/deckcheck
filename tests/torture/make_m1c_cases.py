"""Write the M1c torture cases. Each asks LS-DYNA one question about how it reads fields. Run once; output is
committed. LS-DYNA's answers go into each case's expected.toml (M1c plan, Task 1)."""
from pathlib import Path

HERE = Path(__file__).parent


def i10(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals)


def i20(*vals) -> str:
    return "".join(f"{v:>20}" for v in vals)


HEAD = "*KEYWORD\n*TITLE\ndeckcheck torture: {}\n*CONTROL_TERMINATION\n    1.0E-6\n"
PART = "*PART\nplate\n" + i10(1, 1, 1) + "\n"
SECTION = "*SECTION_SHELL\n" + i10(1, 2) + "\n" + i10(1.0, 1.0, 1.0, 1.0) + "\n"
MAT = "*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n"
MESH = ("*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2            10.0             0.0             0.0\n"
        "       3            10.0            10.0             0.0\n"
        "       4             0.0            10.0             0.0\n"
        "*ELEMENT_SHELL\n"
        "       1       1       1       2       3       4\n")
BASE = PART + SECTION + MAT + MESH
def contact(ssid: int, sstyp: int) -> str:
    return ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(ssid, 0, sstyp, 0) + "\n"
            + i10(0.0, 0.0) + "\n" + i10(1.0, 1.0) + "\n")


def nodes_to_surface(nsid: int) -> str:  # a single-surface contact can't take a node set (Error 11089)
    return ("*CONTACT_NODES_TO_SURFACE\n" + i10(nsid, 1, 4, 3) + "\n"
            + i10(0.0, 0.0) + "\n" + i10(1.0, 1.0) + "\n")


def velocity(id_: int, styp: int) -> str:
    return "*INITIAL_VELOCITY_GENERATION\n" + i10(id_, styp, 0.0, 0.0, 0.0, 1.0) + "\n" + i10(0.0) + "\n"



SET_PART_1 = "*SET_PART_LIST\n" + i10(1) + "\n" + i10(1) + "\n"
GOOD_MAT = "*KEYWORD\n" + MAT + "*END\n"


def deck(title: str, body: str) -> str:
    return HEAD.format(title) + body + "*END\n"


def mat24(lcss: int) -> str:  # piecewise linear plasticity, strain-rate table lcss
    return ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n" + i10(1, "7.85E-9", "210000.0", 0.3, 200.0) + "\n"
            + i10(0.0, 0.0, lcss) + "\n" + i10(*[0.0] * 8) + "\n" + i10(*[0.0] * 8) + "\n")


def curve(lcid: int) -> str:
    return "*DEFINE_CURVE\n" + i10(lcid) + "\n" + i20(0.0, 200.0) + "\n" + i20(1.0, 300.0) + "\n"


def table(rows: list[tuple[float, int]]) -> str:
    return "*DEFINE_TABLE\n" + i10(10) + "\n" + "".join(f"{v:>20}{c:>10}\n" for v, c in rows)


LONG_BASE = ("*PART\nplate\n" + i20(1, 1, 1) + "\n"
             + "*SECTION_SHELL\n" + i20(1, 2) + "\n" + i20(1.0, 1.0, 1.0, 1.0) + "\n"
             + "*MAT_ELASTIC\n" + i20(1, "7.85E-9", "210000.0", 0.3) + "\n"
             + "*NODE\n" + "".join(i20(n, x, y, 0.0) + "\n" for n, x, y in
                                   [(1, 0.0, 0.0), (2, 10.0, 0.0), (3, 10.0, 10.0), (4, 0.0, 10.0)])
             + "*ELEMENT_SHELL\n" + i20(1, 1, 1, 2, 3, 4) + "\n")

CASES = {
    "table_dangling": {  # Does LS-DYNA read DEFINE_TABLE's curve-id column (a missing id is an error)?
        "main.k": deck("table row names a missing curve",
                       BASE.replace(MAT, mat24(10)) + table([(0.0, 99), (1.0, 6)]) + curve(5) + curve(6))},
    "table_ids": {  # The same table with existing ids: the control for table_dangling
        "main.k": deck("table rows name existing curves",
                       BASE.replace(MAT, mat24(10)) + table([(0.0, 5), (1.0, 6)]) + curve(5) + curve(6))},
    "table_before": {  # Are the row ids honoured when the curves come before the table?
        "main.k": deck("table curves defined before the table",
                       BASE.replace(MAT, mat24(10)) + curve(5) + curve(6) + table([(0.0, 5), (1.0, 6)]))},
    "contact_type2_bad": {  # sstyp 2: is ssid a part set? (part 1 exists, part set 1 does not)
        "main.k": deck("contact type 2 without part set", BASE + contact(1, 2))},
    "contact_type3_bad": {  # sstyp 3: is ssid a part? (part set 99 exists, part 99 does not)
        "main.k": deck("contact type 3 without part", BASE + "*SET_PART_LIST\n" + i10(99) + "\n" + i10(1) + "\n"
                       + contact(99, 3))},
    "contact_type4_bad": {  # sstyp 4: is ssid a node set? (part set 1 exists, node set 1 does not)
        "main.k": deck("contact type 4 without node set", BASE + SET_PART_1 + nodes_to_surface(1))},
    "contact_type2_none": {  # sstyp 2 control: neither part set 99 nor part 99 exists
        "main.k": deck("contact type 2 with no part set or part", BASE + contact(99, 2))},
    "velocity_styp1_bad": {  # styp 1: is id a part set? (part 1 exists, part set 1 does not)
        "main.k": deck("velocity styp 1 without part set", BASE + velocity(1, 1))},
    "velocity_styp1_none": {  # styp 1 control: neither part set 99 nor part 99 exists
        "main.k": deck("velocity styp 1 with no part set or part", BASE + velocity(99, 1))},
    "velocity_styp3_bad": {  # styp 3: is id a node set? (part set 1 exists, node set 1 does not)
        "main.k": deck("velocity styp 3 without node set", BASE + SET_PART_1 + velocity(1, 3))},
    "inc_path_in_include": {  # Does an *INCLUDE_PATH inside an included file apply to later includes?
        "main.k": deck("include path inside an include", "*INCLUDE\nsub/a.k\n*INCLUDE\nmat.k\n"
                       + PART + SECTION + MESH),
        "sub/a.k": "*KEYWORD\n*INCLUDE_PATH\nlib\n*END\n",
        "lib/mat.k": GOOD_MAT},
    "inc_blank_in_continuation": {  # Does a blank card end a ' +' continued name, or is it skipped?
        "main.k": deck("blank card inside a continued name", "*INCLUDE\nsub/ +\n\nmat.k\n" + PART + SECTION + MESH),
        "sub/mat.k": GOOD_MAT},
    "inc_empty": {  # Is an *INCLUDE with no filename card accepted (nothing read)?
        "main.k": deck("include with no filename", "*INCLUDE\n" + BASE)},
    "long_keyword": {  # Does *KEYWORD LONG=Y make every card 20 wide? (LONG=S is the standard format)
        "main.k": HEAD.format("long keyword").replace("*KEYWORD\n", "*KEYWORD LONG=Y\n").replace(
            "    1.0E-6\n", i20("1.0E-6") + "\n") + LONG_BASE + "*END\n"},
    "long_section": {  # In '+' format, does an 8-field card stay on one 160-column line?
        "main.k": deck("long section card on one line",
                       BASE.replace(SECTION, "*SECTION_SHELL +\n" + i20(1, 2, 1.0, 2, 1.0, 0, 0, 1) + "\n"
                                    + i20(1.0, 1.0, 1.0, 1.0) + "\n"))},
    "parameter_ref": {  # Is &name substituted in an id field?
        "main.k": deck("parameter in an id field",
                       "*PARAMETER\nI mm               1\n" + BASE.replace(PART, "*PART\nplate\n"
                                                                            + i10(1, 1, "&mm") + "\n"))},
    "spc_set_id": {  # M0 defect: the _ID card comes before the main card
        "main.k": deck("boundary spc set with id",
                       BASE + "*SET_NODE_LIST\n" + i10(1) + "\n" + i10(1, 2) + "\n"
                       + "*BOUNDARY_SPC_SET_ID\n" + i10(7) + "fixed edge\n" + i10(1, 0, 1, 1, 1, 1, 1, 1) + "\n")},
    "spc_set_none": {  # Does *BOUNDARY_SPC_SET reject a missing node set? (the offset probe saw it accepted)
        "main.k": deck("boundary spc names a missing node set",
                       BASE + "*BOUNDARY_SPC_SET\n" + i10(99, 0, 1, 1, 1, 1, 1, 1) + "\n")},
    "zero_ref": {  # M0 defect: 0 in a reference field is no reference (eosid, hgid, tmid all 0)
        "main.k": deck("zero references", BASE.replace(PART, "*PART\nplate\n" + i10(1, 1, 1, 0, 0, 0, 0, 0) + "\n"))},
    # Task 7 (corpus): cards left after the layout, and definers the corpus found
    "repeat_velocity": {  # Is a second two-card instance under one *INITIAL_VELOCITY_GENERATION read? (99: no node set)
        "main.k": deck("velocity generation repeated", BASE + velocity(1, 2) + velocity(99, 3).split("\n", 1)[1])},
    "repeat_mat": {  # Is a second *MAT_ELASTIC line another material? The part uses material 2, defined only there
        "main.k": deck("material repeated", BASE.replace(MAT, MAT + i10(2, "7.85E-9", "210000.0", 0.3) + "\n")
                       .replace(PART, "*PART\nplate\n" + i10(1, 1, 2) + "\n"))},
    "repeat_history_id": {  # Is a second *DATABASE_HISTORY_NODE_ID line read as another instance? (node 99 missing)
        "main.k": deck("history node repeated", BASE + "*DATABASE_HISTORY_NODE_ID\n" + i10(1) + "first\n"
                       + i10(99) + "second\n")},
    "repeat_load_node_set": {  # Is a second *LOAD_NODE_SET line read as another instance? (node set 99 missing)
        "main.k": deck("load node set repeated", BASE + "*SET_NODE_LIST\n" + i10(1) + "\n" + i10(1, 2) + "\n"
                       + "*LOAD_NODE_SET\n" + i10(1, 3, 1, 1.0) + "\n" + i10(99, 3, 1, 1.0) + "\n" + curve(1))},
    "nodal_rigid_part": {  # Does *CONSTRAINED_NODAL_RIGID_BODY's pid define a part a rigid motion can name?
        "main.k": deck("motion on a nodal rigid body", BASE + "*SET_NODE_LIST\n" + i10(1) + "\n" + i10(1, 2) + "\n"
                       + "*CONSTRAINED_NODAL_RIGID_BODY\n" + i10(5, 0, 1) + "\n"
                       + "*BOUNDARY_PRESCRIBED_MOTION_RIGID\n" + i10(5, 1, 2, 1) + "\n" + curve(1))},
    "nodal_rigid_none": {  # control: the motion names part 6, which nothing defines
        "main.k": deck("motion on a missing part", BASE + "*SET_NODE_LIST\n" + i10(1) + "\n" + i10(1, 2) + "\n"
                       + "*CONSTRAINED_NODAL_RIGID_BODY\n" + i10(5, 0, 1) + "\n"
                       + "*BOUNDARY_PRESCRIBED_MOTION_RIGID\n" + i10(6, 1, 2, 1) + "\n" + curve(1))},
    "set_general_rows": {  # Is a second option row of *SET_NODE_GENERAL read? (part 99 missing)
        "main.k": deck("general set rows", BASE + "*SET_NODE_GENERAL\n" + i10(1) + "\n" + "PART      " + i10(1) + "\n"
                       + "PART      " + i10(99) + "\n" + nodes_to_surface(1))},
}

for name, files in CASES.items():
    for rel, text in files.items():
        path = HERE / name / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("latin-1"))
