# Scenario D - PACKET DROPS: a 3% random error model on the primary link R1->R2.
source [file join [file dirname [info script]] common.tcl]

set em [new ErrorModel]
$em unit pkt
$em set rate_ 0.03
$em ranvar [new RandomVariable/Uniform]
$em drop-target [new Agent/Null]
$ns lossmodel $em $n1 $n2

set ftp [make_tcp_flow $ns $n0 $n4 1]
set cbr [make_cbr_flow $ns $n0 $n5 2 0.3Mb]

$ns at 0.5 "$ftp start"
$ns at 0.5 "$cbr start"
$ns at 9.5 "$ftp stop"
$ns at 9.5 "$cbr stop"
$ns at 10.0 "finish"
$ns run
