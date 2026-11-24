# Scenario A - NORMAL network: TCP A->B and a light UDP stream A->C, no faults.
source [file join [file dirname [info script]] common.tcl]

set ftp [make_tcp_flow $ns $n0 $n4 1]
set cbr [make_cbr_flow $ns $n0 $n5 2 0.3Mb]

$ns at 0.5 "$ftp start"
$ns at 0.5 "$cbr start"
$ns at 9.5 "$ftp stop"
$ns at 9.5 "$cbr stop"
$ns at 10.0 "finish"
$ns run
