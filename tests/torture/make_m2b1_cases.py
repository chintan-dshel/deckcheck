"""M2b.1 torture cases (docs/plans/2026-10-31-m2b1-trial-fixes.md, Tasks 4-5): a required reference left blank or 0,
and a definition whose own id is blank or 0 (Chintan's trial: a card pasted 3 columns to the right). Built on the
M1d base model. Writes main.k always; writes expected.toml once VERDICT holds LS-DYNA's answer for the case.
Run: .venv/Scripts/python tests/torture/make_m2b1_cases.py"""
import json

from make_m1d_cases import BASE, HERE, i10, i20

PART_CARD = i10(1, 1, 1)
SHELL = "       1       1       1       2       3       4"
DC005_MAT1 = {"code": "DC005", "line": 13, "columns": [9, 10]}       # MAT 1 left unused by a blank mid
DC005_SECTION1 = {"code": "DC005", "line": 10, "columns": [9, 10]}

# name -> (title, base text replacement or None, extra text from line 28, dangling refs, DC003/DC005 findings)
CASES = {
    "m2b1_part_mid_blank": ("part with a blank mid", (PART_CARD, i10(1, 1)), "",
                            [("MAT", 0, 8, [20, 30])], [DC005_MAT1]),
    "m2b1_part_mid_zero": ("part with mid 0", (PART_CARD, i10(1, 1, 0)), "",
                           [("MAT", 0, 8, [29, 30])], [DC005_MAT1]),
    "m2b1_part_secid_blank": ("part with a blank secid", (PART_CARD, i10(1, "", 1)), "",
                              [("SECTION", 0, 8, [10, 20])], [DC005_SECTION1]),
    "m2b1_shell_pid_blank": ("shell element with a blank part id",
                             (SHELL, "       1               1       2       3       4"), "",
                             [("PART", 0, 20, [8, 16])], []),
    "m2b1_mat_shifted": ("a second material pasted 3 columns to the right", None,
                         "*MAT_ELASTIC\n   " + i10(2, "7.85E-9", "210000.0", 0.3) + "\n",
                         [], [{"code": "DC003", "line": 29, "columns": [0, 10]}]),
    "m2b1_mat_zero": ("a second material with id 0", None,
                      "*MAT_ELASTIC\n" + i10(0, "7.85E-9", "210000.0", 0.3) + "\n",
                      [], [{"code": "DC003", "line": 29, "columns": [9, 10]}]),
    "m2b1_section_blank": ("a second section with a blank id", None,
                           "*SECTION_SHELL\n" + i10("", 2) + "\n" + i10(2.0, 2.0, 2.0, 2.0) + "\n",
                           [], [{"code": "DC003", "line": 29, "columns": [0, 10]}]),
    "m2b1_part_blank_id": ("a second part with a blank id", None, "*PART\nsecond\n" + i10("", 1, 1) + "\n",
                           [], [{"code": "DC003", "line": 30, "columns": [0, 10]}]),
    "m2b1_curve_blank": ("a second curve with a blank id", None,
                         "*DEFINE_CURVE\n" + i10("", 0, 2.0) + "\n" + i20(0.0, 2.0) + "\n" + i20(1.0, 2.0) + "\n",
                         [], [{"code": "DC003", "line": 29, "columns": [0, 10]}]),
    "m2b1_set_node_blank": ("a second node set with a blank id", None,
                            "*SET_NODE_LIST\n" + i10("", 0.0) + "\n" + i10(3, 4) + "\n",
                            [], [{"code": "DC003", "line": 29, "columns": [0, 10]}]),
    "m2b1_hourglass_blank": ("an hourglass control with a blank id", None, "*HOURGLASS\n" + i10("", 4) + "\n",
                             [], [{"code": "DC003", "line": 29, "columns": [0, 10]}]),
    "m2b1_trailing_blank_card": ("a blank line after the material card", None, "*MAT_ELASTIC\n"
                                 + i10(2, "7.85E-9", "210000.0", 0.3) + "\n\n", [],
                                 [{"code": "DC005", "line": 29, "columns": [9, 10]}]),
}

# LS-DYNA R16.1 Student, 2026-10-31 (bakeoff/lsdyna_oracle.py on each folder): name -> (lsdyna_valid, deciding line)
VERDICT: dict[str, tuple[bool, str]] = {
    "m2b1_part_mid_blank": (False, "Error 10304: MATERIAL ID 0 does not exist (CHECKING MATERIAL INPUT Part ID= 1)"),
    "m2b1_part_mid_zero": (False, "Error 10304: MATERIAL ID 0 does not exist (CHECKING MATERIAL INPUT Part ID= 1)"),
    "m2b1_part_secid_blank": (False, "Error 10125, keyword input phase failed"),
    "m2b1_shell_pid_blank": (False, "Error 20389 and Error 20230 for the shell element"),
    "m2b1_mat_shifted": (True, "accepted, no warning: the shifted card's mid field is blank, so the material is id 0"),
    "m2b1_mat_zero": (True, "accepted, no warning"),
    "m2b1_section_blank": (True, "accepted, no warning"),
    "m2b1_part_blank_id": (True, "accepted, no warning"),
    "m2b1_curve_blank": (True, "accepted, no warning"),
    "m2b1_set_node_blank": (True, "accepted, no warning"),
    "m2b1_hourglass_blank": (True, "accepted, no warning"),
    "m2b1_trailing_blank_card": (True, "accepted, no warning: a blank line after a card is no second definition"),
}


def expected(name: str, dangling, findings, valid: bool, note: str) -> str:
    lines = [f"lsdyna_valid = {'true' if valid else 'false'}", "findings = []", f"note = {json.dumps(note)}"]
    if dangling:
        rows = ", ".join(f'{{kind = "{k}", id = {i}, file = "main.k", line = {ln}, columns = [{c[0]}, {c[1]}]}}'
                         for k, i, ln, c in dangling)
        lines += ["", "[index]", f"dangling = [{rows}]"]
    for f in findings:
        lines += ["", "[[diagnostics]]", f'code = "{f["code"]}"', 'severity = "warning"', 'file = "main.k"',
                  f'line = {f["line"]}', f'columns = [{f["columns"][0]}, {f["columns"][1]}]']
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    for name, (title, replace, extra, dangling, findings) in CASES.items():
        text = BASE.format(title=title, extra=extra)
        if replace:
            assert text.count(replace[0]) == 1, name
            text = text.replace(*replace)
        folder = HERE / name
        folder.mkdir(exist_ok=True)
        (folder / "main.k").write_bytes(text.encode("latin-1"))
        if name in VERDICT:
            (folder / "expected.toml").write_text(expected(name, dangling, findings, *VERDICT[name]), encoding="utf-8")
