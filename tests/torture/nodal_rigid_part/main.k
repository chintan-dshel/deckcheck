*KEYWORD
*TITLE
deckcheck torture: motion on a nodal rigid body
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
*SET_NODE_LIST
         1
         1         2
*CONSTRAINED_NODAL_RIGID_BODY
         5         0         1
*BOUNDARY_PRESCRIBED_MOTION_RIGID
         5         1         2         1
*DEFINE_CURVE
         1
                 0.0               200.0
                 1.0               300.0
*END
