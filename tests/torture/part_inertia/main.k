*KEYWORD
*TITLE
deckcheck torture: part inertia
*CONTROL_TERMINATION
    1.0E-6
*PART_INERTIA
plate
$#     pid     secid       mid
         1         1         1
$#      xc        yc        zc        tm      ircs    nodeid
       5.0       5.0       0.0    1.0E-3         0         0
$#     ixx       ixy       ixz       iyy       iyz       izz
       1.0       0.0       0.0       1.0       0.0       1.0
$#     vtx       vty       vtz       vrx       vry       vrz
       0.0       0.0       0.0       0.0       0.0       0.0
*PART
anchor
$#     pid     secid       mid
         2         1         1
*SECTION_SHELL
         1         2
       1.0       1.0       1.0       1.0
*MAT_RIGID
$#     mid        ro         e        pr
         1   7.85E-9  210000.0       0.3
$#     cmo      con1      con2
       0.0       0.0       0.0
$# lco/a1        a2        a3        v1        v2        v3
       0.0       0.0       0.0       0.0       0.0       0.0
*SET_PART_LIST
$#     sid
         1
$#    pid1
         1
*CONTACT_AUTOMATIC_SINGLE_SURFACE
$#    ssid      msid     sstyp     mstyp    sboxid    mboxid       spr       mpr
         1         0         2         0         0         0         0         0
$#      fs        fd        dc        vc       vdc    penchk        bt        dt
       0.0       0.0       0.0       0.0       0.0         0       0.01.0000E20
$#     sfs       sfm       sst       mst      sfst      sfmt       fsf       vsf
       1.0       1.0       0.0       0.0       1.0       1.0       1.0       1.0
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5            20.0             0.0             0.0
       6            30.0             0.0             0.0
       7            30.0            10.0             0.0
       8            20.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
*END
