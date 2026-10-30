*KEYWORD
*TITLE
deckcheck torture: node 1 defined twice at the same coordinates
*CONTROL_TERMINATION
    1.0E-6
*PART
plate
         1         1         1
*SECTION_SHELL
         1         2
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1   7.85E-9  210000.0       0.3
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*DEFINE_CURVE
         1
                 0.0                 1.0
                 1.0                 1.0
*SET_NODE_LIST
         1
         1         2
*NODE
       1             0.0             0.0             0.0
*END
