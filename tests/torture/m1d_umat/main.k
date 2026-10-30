*KEYWORD
*TITLE
deckcheck torture: user-defined material (umat41) on a second part
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
*PART
user material
         2         1         2
*MAT_USER_DEFINED_MATERIAL_MODELS
         2   7.85E-9        41         4         0         0         3         4
         0         0         0         0         0         0
  210000.0       0.3  175000.0   80769.2
*END
