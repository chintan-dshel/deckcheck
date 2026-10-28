"""Write the include and *END torture cases. Each asks LS-DYNA one question about how it reads files.
Run once; output is committed. LS-DYNA's answers go into each case's expected.toml (M1b plan, Task 1)."""
from pathlib import Path

HERE = Path(__file__).parent

HEAD = "*KEYWORD\n*TITLE\ndeckcheck torture: {}\n*CONTROL_TERMINATION\n    1.0E-6\n"
PART = "*PART\nplate\n         1         1         1\n"
SECTION = "*SECTION_SHELL\n         1         2\n       1.0       1.0       1.0       1.0\n"
MAT = "*MAT_ELASTIC\n         {}   7.85E-9  210000.0       0.3\n"
MESH = ("*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2            10.0             0.0             0.0\n"
        "       3            10.0            10.0             0.0\n"
        "       4             0.0            10.0             0.0\n"
        "*ELEMENT_SHELL\n"
        "       1       1       1       2       3       4\n")
GOOD = "*KEYWORD\n" + MAT.format(1) + "*END\n"  # material 1: what part 1 needs
BAD = "*KEYWORD\n" + MAT.format(2) + "*END\n"   # material 2 only: reading this file leaves part 1 without material


def main_deck(title: str, includes: str, body: str = PART + SECTION + MESH) -> str:
    return HEAD.format(title) + includes + body + "*END\n"


def part_file(text: str) -> str:
    return "*KEYWORD\n" + text + "*END\n"


WITH_MAT = PART + SECTION + MAT.format(1) + MESH

CASES = {
    "inc_nested_sibling": {  # Is a nested include searched in the including file's folder?
        "main.k": main_deck("nested include beside its includer", "*INCLUDE\nsub/a.k\n"),
        "sub/a.k": part_file("*INCLUDE\nb.k\n"),
        "sub/b.k": GOOD},
    "inc_nested_main": {  # Is a nested include searched in the main deck's folder?
        "main.k": main_deck("nested include beside main", "*INCLUDE\nsub/a.k\n"),
        "sub/a.k": part_file("*INCLUDE\nb.k\n"),
        "b.k": GOOD},
    "inc_nested_both": {  # If both folders hold the file, which wins?
        "main.k": main_deck("nested include in both folders", "*INCLUDE\nsub/a.k\n"),
        "sub/a.k": part_file("*INCLUDE\nb.k\n"),
        "sub/b.k": GOOD,
        "b.k": BAD},
    "inc_path_precedence": {  # Does an *INCLUDE_PATH folder win over the main deck's folder?
        "main.k": main_deck("include path precedence", "*INCLUDE_PATH\nlib\n*INCLUDE\nmat.k\n"),
        "mat.k": BAD,
        "lib/mat.k": GOOD},
    "inc_path_relative": {  # Is *INCLUDE_PATH_RELATIVE relative to the file holding it, or to the main deck?
        "main.k": main_deck("include path relative", "*INCLUDE\nsub/a.k\n"),
        "sub/a.k": part_file("*INCLUDE_PATH_RELATIVE\nlib\n*INCLUDE\nmat.k\n"),
        "sub/lib/mat.k": GOOD,
        "lib/mat.k": BAD},
    "inc_path_backslash": {  # VIVA+'s form: a Windows path with a trailing backslash
        "main.k": main_deck("include path with backslashes", "*INCLUDE_PATH\n.\\lib\\\n*INCLUDE\nmat.k\n"),
        "lib/mat.k": GOOD},
    "inc_path_late": {  # Does an *INCLUDE_PATH apply to an *INCLUDE that comes before it?
        "main.k": main_deck("include path after the include", "*INCLUDE\nmat.k\n*INCLUDE_PATH\nlib\n"),
        "lib/mat.k": GOOD},
    "inc_multi": {  # Does one *INCLUDE read several filename cards?
        "main.k": main_deck("two files on one include", "*INCLUDE\nmat.k\nsec.k\n", PART + MESH),
        "mat.k": GOOD,
        "sec.k": part_file(SECTION)},
    "inc_continuation": {  # Does a filename ending in ' +' continue on the next line?
        "main.k": main_deck("filename continued", "*INCLUDE\nsub/ +\nmat.k\n"),
        "sub/mat.k": GOOD},
    "inc_cycle": {  # What does LS-DYNA do with a.k -> b.k -> a.k?
        "main.k": main_deck("include cycle", "*INCLUDE\na.k\n", WITH_MAT),
        "a.k": part_file("*INCLUDE\nb.k\n"),
        "b.k": part_file("*INCLUDE\na.k\n")},
    "inc_transform": {  # *INCLUDE_TRANSFORM with node and element offsets, laid out like the Yaris
        "main.k": main_deck("include transform", "",
                            PART + SECTION + MAT.format(1)
                            + "*INCLUDE_TRANSFORM\nmesh.k\n       100       100\n\n\n\n"),
        "mesh.k": part_file(MESH)},
    "end_main": {  # Is text after *END in the main deck ignored?
        "main.k": main_deck("text after end", "", WITH_MAT) + "*NOT_A_KEYWORD\n         1\n"},
    "end_include": {  # Does *END in an include end only that file, the parent continuing after it?
        "main.k": main_deck("end inside an include", "*INCLUDE\nmat.k\n"),
        "mat.k": GOOD + "*NOT_A_KEYWORD\n         1\n"},
}

for name, files in CASES.items():
    for rel, text in files.items():
        path = HERE / name / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("latin-1"))  # '\n' endings on every platform
