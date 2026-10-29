*KEYWORD
*TITLE
deckcheck torture: include transform
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
*INCLUDE_TRANSFORM
mesh.k
       100       100



*END
