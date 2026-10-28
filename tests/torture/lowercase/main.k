*keyword
*title
deckcheck torture: lowercase
*control_termination
    1.0E-6
*part
plate
         1         1         1
*section_shell
         1         2
       1.0       1.0       1.0       1.0
*mat_elastic_title
steel
         1   7.85E-9  210000.0       0.3
*node
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*element_shell
       1       1       1       2       3       4
*end
