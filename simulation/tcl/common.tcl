# AegisNet NS2 topology shared by all scenarios (sourced by each scenario script).
# Mirrors the Linux lab:  n0=PC A  n1=R1  n2=R2  n3=R3  n4=PC B  n5=PC C
#
#   n0 --10Mb-- n1 ==2Mb(primary)== n2 --10Mb-- n4
#                 \                /
#                  2Mb          2Mb
#                    \          /
#                      n3 ------ (backup path via R3)
#                       |
#                      10Mb
#                       n5
#
# NOTE: everything produced by NS2 is SIMULATED. It is never a measurement of this computer.

set ns [new Simulator]
$ns rtproto DV                       ;# distance-vector dynamic routing inside the simulation

set tf [open out.tr w]               ;# trace file parsed by simulation/trace_parser.py
$ns trace-all $tf

set n0 [$ns node]
set n1 [$ns node]
set n2 [$ns node]
set n3 [$ns node]
set n4 [$ns node]
set n5 [$ns node]

$ns duplex-link $n0 $n1 10Mb 5ms  DropTail
$ns duplex-link $n1 $n2 2Mb  10ms DropTail      ;# primary inter-router link
$ns duplex-link $n1 $n3 2Mb  15ms DropTail
$ns duplex-link $n3 $n2 2Mb  15ms DropTail
$ns duplex-link $n2 $n4 10Mb 5ms  DropTail
$ns duplex-link $n3 $n5 10Mb 5ms  DropTail

# Flow 1: TCP (FTP) from PC A to PC B  - the headline flow of every scenario
proc make_tcp_flow {ns src dst fid} {
    set tcp [new Agent/TCP]
    $tcp set fid_ $fid
    $tcp set packetSize_ 1000
    $ns attach-agent $src $tcp
    set sink [new Agent/TCPSink]
    $ns attach-agent $dst $sink
    $ns connect $tcp $sink
    set ftp [new Application/FTP]
    $ftp attach-agent $tcp
    return $ftp
}

# UDP constant-bit-rate flow
proc make_cbr_flow {ns src dst fid rate} {
    set udp [new Agent/UDP]
    $udp set fid_ $fid
    $ns attach-agent $src $udp
    set null [new Agent/Null]
    $ns attach-agent $dst $null
    $ns connect $udp $null
    set cbr [new Application/Traffic/CBR]
    $cbr set packetSize_ 1000
    $cbr set rate_ $rate
    $cbr attach-agent $udp
    return $cbr
}

proc finish {} {
    global ns tf
    $ns flush-trace
    close $tf
    exit 0
}
