# Scenario B - CONGESTION: a 1.6 Mb/s UDP stream A->B shares the 2 Mb/s primary link with TCP,
# the router queue is small, and at t=6s the primary link bandwidth is reduced (changing conditions).
source [file join [file dirname [info script]] common.tcl]

$ns queue-limit $n1 $n2 10

set ftp [make_tcp_flow $ns $n0 $n4 1]
set cbr [make_cbr_flow $ns $n0 $n5 2 0.3Mb]
set hog [make_cbr_flow $ns $n0 $n4 3 1.6Mb]       ;# background flow that creates the congestion

$ns at 0.5 "$ftp start"
$ns at 0.5 "$cbr start"
$ns at 2.0 "$hog start"
$ns at 6.0 "$ns bandwidth $n1 $n2 1.5Mb duplex"   ;# network condition changes mid-run
$ns at 9.5 "$ftp stop"
$ns at 9.5 "$cbr stop"
$ns at 9.5 "$hog stop"
$ns at 10.0 "finish"
$ns run
