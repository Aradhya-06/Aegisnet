# Scenario C - FAILED LINK: the primary link R1-R2 goes down at t=4s and comes back at t=8s.
# Distance-vector routing (rtproto DV) detects it and moves TCP onto the longer path via R3.
source [file join [file dirname [info script]] common.tcl]

set ftp [make_tcp_flow $ns $n0 $n4 1]
set cbr [make_cbr_flow $ns $n0 $n5 2 0.3Mb]

$ns rtmodel-at 4.0 down $n1 $n2
$ns rtmodel-at 8.0 up   $n1 $n2

$ns at 0.5 "$ftp start"
$ns at 0.5 "$cbr start"
$ns at 9.5 "$ftp stop"
$ns at 9.5 "$cbr stop"
$ns at 10.0 "finish"
$ns run
