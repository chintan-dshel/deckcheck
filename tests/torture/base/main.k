*KEYWORD
*TITLE
deckcheck torture: base
*CONTROL_TERMINATION
$#  endtim    endcyc     dtmin    endeng    endmas
    1.0E-6
*PART
$#                                                                         title
plate
$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid
         1         1         1
*SECTION_SHELL
$#   secid    elform      shrf       nip     propt   qr/irid     icomp     setyp
         1         2
$#      t1        t2        t3        t4      nloc     marea      idof    edgset
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
$#     mid        ro         e        pr
         1   7.85E-9  210000.0       0.3
*NODE
$#   nid               x               y               z      tc      rc
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
$#   eid     pid      n1      n2      n3      n4
       1       1       1       2       3       4
*END
