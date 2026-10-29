*KEYWORD
*TITLE
deckcheck torture: table curves defined before the table
*CONTROL_TERMINATION
    1.0E-6
*PART
plate
         1         1         1
*SECTION_SHELL
         1         2
       1.0       1.0       1.0       1.0
*MAT_PIECEWISE_LINEAR_PLASTICITY
         1   7.85E-9  210000.0       0.3     200.0
       0.0       0.0        10
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*DEFINE_CURVE
         5
                 0.0               200.0
                 1.0               300.0
*DEFINE_CURVE
         6
                 0.0               200.0
                 1.0               300.0
*DEFINE_TABLE
        10
                 0.0         5
                 1.0         6
*END
