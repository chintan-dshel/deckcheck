*KEYWORD
*TITLE
deckcheck torture: velocity generation repeated
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
*INITIAL_VELOCITY_GENERATION
         1         2       0.0       0.0       0.0       1.0
       0.0
        99         3       0.0       0.0       0.0       1.0
       0.0
*END
