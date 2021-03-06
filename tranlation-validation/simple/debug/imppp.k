require "common.k"

module IMPPP-SYNTAX
  syntax AExp  ::= Int | Id | Call
                 | AExp "/" AExp              [left, strict, klabel(divi)]
                 > AExp "+" AExp              [left, seqstrict, klabel(addi)]
                 | "(" AExp ")"               [bracket]
  syntax BExp  ::= Bool | Id | Call
                 | AExp "<=" AExp             [seqstrict, klabel(lei)]
                 | AExp "==" AExp             [seqstrict]
                 | "!" BExp                   [strict]
                 > BExp "&&" BExp             [left, strict(1), klabel(andi)]
                 | "(" BExp ")"               [bracket]
  syntax Block ::= "{" "}"
                 | "{" Stmt "}"
  syntax Stmt  ::= Block
                 //| Call ";"                  [strict(1)]
                 | Exp ";"                      [strict]
                 | Id "=" Exp ";"            [strict(2)]
                 | "if" "(" BExp ")"
                   Block "else" Block         [strict(1)]
                 | "if" "(" BExp ")" Block    [prefer]
                 | "while" "(" BExp ")" Block
                 | "return" Exp ";"   [strict]
                 | "return" ";"
                 > Stmt Stmt                  [left]
  syntax Pgm ::= Decs

  syntax Dec ::= FunDec | VarDec
  syntax Decs ::= List{Dec,""} [klabel('Decs)]
  syntax VarDec ::= Type Id ";"
  syntax Type ::= "int" | "bool" | "void"
  syntax Param ::= Type Id
  syntax Params ::= List{Param,","} [klabel('Params)]
  syntax FunDec ::= Type Id "(" Params ")" Block

  syntax Exp ::= AExp | BExp
  syntax Exps ::= List{Exp, ","} [klabel('Exps)]
  syntax Call ::= Id "(" Exps ")"   //[strict(2)]

  // APIs
  syntax Id ::=  "#get_next_packet" [token]
                |"#output_packet" [token]
                |"#drop" [token]
                |"#emit" [token]
                |"#reset" [token]
                |"#call_entry_action" [token]
                |"#entry_matches" [token]
                |"#get_next_enrty" [token]
                |"#has_next" [token]
                |"#extract_next" [token]
                |"#has_default_action" [token]
                |"#call_default_action" [token]
                |"#add_payload" [token]


endmodule

module IMPPP
  imports IMPPP-SYNTAX
  imports COMMON


  syntax Id ::= "main" [token]

  syntax Id ::= "b" [token]

  configuration <L2>
                  <k> $PGM:Pgm ~> main ( .Exps ); </k>
                  <state> .Map </state>
                  <funs> .Map </funs>
                  <stack> .List </stack>
                  //API
                  //<in> $consPacketList($packet(@cons(@undef , @cons (@val(0,8,false) , @nil)), 30), $nilPacketList) </in>
                  <in> $consPacketList($packet(@cons(@val(0,8,false) , @cons (@val(0,8,false) , @nil)), 30), $nilPacketList) </in>
                  //<in> $consPacketList($packet(ListItem(@val(0,8,false)) ListItem(@val(0,8,false)), 30), $nilPacketList) </in>
                  //<in> $nilPacketList </in>
                  <out> $nilPacketList </out>
                  <packet>  @nil </packet>
                  <packetout> @nil </packetout>
                  //<table> ListItem($rule(1,$ctr(ListItem(@val(0,8,false))), @rcall (b, $rv(.List)))) </table>
                  //<table> .List </table>
                  <table> $consEntryList($rule(1,$ctr(@cons(@val(0,8,false),  @nil)), @rcall(b, $rv(@nil))), $nilEntryList) </table>
                  <crntE> $nilEntryList </crntE>
                  <ce> .K </ce>
                  <default> $nothing </default>
                  <index> 0 </index>
                </L2>


  syntax IVal ::= Int | Bool
  syntax IVals ::= "@nilIVals" | "@consIVals" "(" IVal "," IVals ")"
  syntax KResult ::= IVal | IVals



  syntax Fun ::= "$fun" "(" Params "," Block ")"
  syntax Cnt ::= "$cnt" "(" Params "," K ")"

  syntax KItem ::= "@bind" "(" IVals "," Params ")"
  rule @bind (@nilIVals , .Params) => .K
  rule <k> @bind (@consIVals(V:IVal , Vs) => Vs , (Type P:Id , Ps:Params ) => Ps) ... </k> <state> (.Map => (P |-> V)) _:Map </state>

  syntax KItem ::= "@unbind" "(" Params ")"
  rule @unbind (.Params) => .K
  rule <k> @unbind ((Type P:Id , Ps:Params ) => Ps) ... </k> <state> M:Map => M[P <- undef] </state>

// AExp
  rule .Exps => @nilIVals
  rule X:Exp , R:Exps => @makeCons(X,R)

  syntax KItem ::= "@makeCons" "(" K /* IVal */ "," K /* IVals */ ")" [strict]
  rule @makeCons(V:IVal,Vs:IVals) => @consIVals(V,Vs)

  syntax Exp ::= IVal
  syntax Exps ::= IVals
  rule <k> X:Id => I ...</k> <state>... X |-> I ...</state>
  /* rule  <k> (F:Id (V:IVals) ~> C:K) => (@bind(V,P) ~> B ~> return;) </k>
        <stack> (.List => ListItem($cnt(P,C))) _:List </stack>
        <funs> (F |-> $fun(P:Params,B:Block)) _:Map </funs>
        <state> S:Map </state>*/

  rule  <k> (@call F:Id (V:IVals) ~> C:K) => (@bind(V,P) ~> B ~> return;) </k>
          <stack> (.List => ListItem($cnt(P,C))) _:List </stack>
          <funs> (F |-> $fun(P:Params,B:Block)) _:Map </funs>
          <state> S:Map </state>

  rule F:Id (V) => @call F (V)
  syntax Exp ::= "@call" Id "(" K /*IVals */ ")" [strict(2)]


  rule I1 / I2 => I1 /Int I2  requires I2 =/=Int 0
  rule I1 + I2 => I1 +Int I2
// BExp
  rule I1 <= I2 => I1 <=Int I2
  rule I1 == I2 => I1 ==Int I2
  rule ! T => notBool T
  rule true && B => B
  rule false && _ => false
// Block
  rule {} => .   [structural]
  rule {S} => S  [structural]
// Stmt
  rule <k> X:Id = I:IVal; => . ...</k> <state>... X |-> (_ => I) ...</state>
  rule S1:Stmt S2:Stmt => S1 ~> S2  [structural]
  rule if (true)  S else _ => S
  rule if (false) _ else S => S
  rule if (B) Blk:Block => if (B) Blk else {}
  rule while (B) S => if (B) {S while (B) S} else {}  [structural]


  rule return ; => return 0; [macro]
  rule <k> return V:IVal ; ~> _ => @unbind(P) ~> V ~> C  </k>
       <stack> (ListItem($cnt(P:Params,C:K)) => .List) _:List </stack>
  rule _:IVal ; => .K
// Pgm
  rule <k> int X ; => .K ... </k> <state> Rho:Map (.Map => X |-> 0) </state> requires notBool (X in keys(Rho))
  rule <k> bool X ; => .K ... </k> <state> Rho:Map (.Map => X|-> false) </state> requires notBool (X in keys(Rho))
  rule <k> _:Type F:Id (P:Params) B:Block => .K ... </k> <funs> Rho:Map (.Map => F|-> $fun(P,B)) </funs>  requires notBool (F in keys(Rho))

//Dec
  rule D:Dec Ds:Decs => D ~> Ds [structural]
  rule .Decs => .K              [structural]



    // APIs

    rule <k> @call #reset (@nilIVals) => 0 ... </k>
         <index> _ => 0 </index>
         <crntE> _ => T </crntE>
         <table> T </table>
         <packetout> _ => @nil </packetout>

    rule <k> @call #output_packet (@nilIVals) => 0 ... </k>
         <packetout> P:Vals </packetout>
         <state> standard_metadata_egress_spec |-> I:Int _:Map </state>
         <out> L:PacketList => $consPacketList($packet(P,I), L) </out>
         when I =/=Int -1

    rule <k> @call #output_packet (@nilIVals) => 1 ... </k>
             <packetout> P:Vals </packetout>
             <state> standard_metadata_egress_spec |-> -1 _:Map </state>

    rule <k> @call #drop (@nilIVals) => 0 ... </k>

    rule <k> @call #emit (@consIVals(V:Int , @consIVals(W:Int , @consIVals(S:Bool , @nilIVals)))) => 0 ... </k>
         <packetout> L:Vals => @cons(@val(V,W,S),L) </packetout>

    rule <k> @call #get_next_packet (@nilIVals) => true ... </k>
         <in> $consPacketList($packet(P:Vals, _:Int), L:PacketList) => L </in>
         <packet> _ => P </packet>

    rule <k> @call #get_next_packet (@nilIVals) => false ... </k>
         <in> $nilPacketList </in>

    rule <k> @call #has_next (@consIVals(_:Int , @nilIVals)) => false ... </k>
         <packet> @nil </packet>
         <index> I:Int </index>

    rule <k> @call #has_next (@consIVals(_:Int , @nilIVals)) => true ... </k>
         <packet> @cons(_,_) </packet>
         <index> I:Int </index>


    rule <k> @call #extract_next (@consIVals(W:Int, @consIVals(S:Bool, @nilIVals))) => V  ... </k>
         <packet> @cons(@val(V:Int, W, S), Vs:Vals) => Vs </packet>
         <index> I:Int => I +Int 1 </index>


    rule <k> @call #get_next_enrty (@nilIVals) => false ... </k>
         <crntE> $nilEntryList </crntE>
    rule <k> @call #get_next_enrty (@nilIVals) => true ... </k>
         <crntE> $consEntryList(R:Rule,L:EntryList) => L </crntE>
         <ce> _ => R </ce>


    rule <k> @call #entry_matches (@consIVals(I:Int , @nilIVals)) => true ... </k>
         //<crntE> $consEntryList($rule(_, $ctr(@cons(@val(I,_,_), @nil)), _), _) </crntE>
         <ce> $rule(_, $ctr(@cons(@val(I,_,_), @nil)), _) </ce>

    rule <k> @call #entry_matches (@consIVals(I:Int , @nilIVals)) => false ... </k>
         //<crntE> $consEntryList($rule(_, $ctr(@cons(@val(J:Int,_,_), @nil)), _), _) </crntE>
         <ce> $rule(_, $ctr(@cons(@val(J:Int,_,_), @nil)), _) </ce>
      when I =/=Int J

    rule <k> @call #call_entry_action (@nilIVals) => @call A (@vals2IVals(L)) ... </k>
         //<crntE> $consEntryList($rule(_, _, @rcall(A:Id, $rv (L:Vals) )), _) </crntE>
         <ce> $rule(_, _, @rcall(A:Id, $rv (L:Vals) )) </ce>

    rule <k> @call #has_default_action (@nilIVals) => true ... </k>
         <default> @rcall (_,_) </default>

    rule <k> @call #has_default_action (@nilIVals) => false ... </k>
         <default> $nothing </default>

    rule <k> @call #call_default_action (@nilIVals) => @call A (@vals2IVals(L))  ... </k>
         <default> @rcall(A:Id, $rv (L:Vals)) </default>

    rule <k> @call #add_payload (@nilIVals) => 0 ... </k>
         <packet> @nil </packet>

    rule <k> @call #add_payload (@nilIVals) ... </k>
         <packet> @cons(V:Val, L:Vals) => L </packet>
         <packetout> PO => @cons(V, PO) </packetout>



   //syntax KResult ::= Val | Vals
   //syntax KResult ::= Int

    //syntax IVals ::= "#vals2IVals" "(" Vals ")" [function]
    syntax IExp ::= "@vals2IVals" "(" Vals ")"
    rule @vals2IVals(@nil) => @nilIVals
    //rule @vals2IVals(@cons(V:Val, L:Vals)) => @makeCons(#val2Int(V) , @vals2IVals(L))
    rule @vals2IVals(@cons(V:Val, L:Vals)) => @makeCons(#egressVal2Int(V) , @vals2IVals(L))

    //syntax Int ::= "#val2Int" "(" Val ")" [function,smtlib(val_to_int)]
    //rule #val2Int(@val(I:Int,_,_)) => I [smt-lemma]

    syntax Id ::= "standard_metadata_egress_spec" [token]


endmodule
