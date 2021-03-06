header_type ht {
    fields {
        f1 : 4;
        f2 : 4;
    }
}

header_type mdt {
    fields {
        f : 8;
    }
}

header ht h;
metadata mdt md;

parser start{
    extract(h);
    return ingress;
}

parser_exception p4_pe_out_of_packet {
    set_metadata(md.f, 1);
    parser_drop;
}

action noop() {

}

table t {
    reads {
        h.f1 : exact;
    }
    actions {
        noop;
    }
}

control ingress{
    apply(t);
}