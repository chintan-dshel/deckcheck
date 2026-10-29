*KEYWORD
*TITLE
deckcheck torture: include path precedence
*CONTROL_TERMINATION
    1.0E-6
*INCLUDE_PATH
lib
*INCLUDE
mat.k
*PART
plate
         1         1         1
*SECTION_SHELL
         1         2
       1.0       1.0       1.0       1.0
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*END
