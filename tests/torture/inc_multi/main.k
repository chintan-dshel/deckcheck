*KEYWORD
*TITLE
deckcheck torture: two files on one include
*CONTROL_TERMINATION
    1.0E-6
*INCLUDE
mat.k
sec.k
*PART
plate
         1         1         1
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*END
