*KEYWORD
$ a comment before anything
*TITLE
deckcheck torture: comments
*CONTROL_TERMINATION
$ comment between keyword line and card
    1.0E-6
*PART
$ title card next
plate
$ ids card next
         1         1         1
*SECTION_SHELL
         1         2
$ thickness card next
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
$#     mid        ro         e        pr
$ a second comment line
         1   7.85E-9  210000.0       0.3
*NODE
       1             0.0             0.0             0.0
$ comment between node rows
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*END
