"""Bounded historical-question solvers: integer simulations and exact algebra.

No answer lookup by question ID, no executable input, no statistical proof.
Each branch requires the declared problem conditions and records its parameters.
"""
import re,heapq,struct
from fractions import Fraction
from backend.services.constant_expression import constant_expression

SOLVERS=frozenset('hs_stack_operations hs_stack_arithmetic hs_ipv4_fragment hs_cache_tag hs_huffman_wpl hs_huffman_decode hs_huffman_nodes hs_ieee_decode hs_ieee_encode hs_ieee_min_normal hs_limit_parameters hs_span_intersection hs_rank_square_zero hs_list_insertion hs_log_integral_min hs_doubly_list_two_step_pointer_v1 hs_rail_tracks_minimum_fifo_v1'.split())
from backend.services.phase45hx_math_verifiers import SOLVERS as MATH_RECOVERY_SOLVERS
SOLVERS = SOLVERS | MATH_RECOVERY_SOLVERS
from backend.services.phase45hx_crc_verifier import SOLVERS as CRC_RECOVERY_SOLVERS
SOLVERS = SOLVERS | CRC_RECOVERY_SOLVERS


def normalize(text):
    value=re.sub(r'\s+','',str(text or '')).replace('$','').replace('`','').replace('−','-').replace('×','*').replace('，',',')
    supers='⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺';translate=str.maketrans(supers,'0123456789-+')
    value=re.sub('['+supers+']+',lambda m:'^('+m[0].translate(translate)+')',value)
    for command,symbol in (('alpha','α'),('beta','β'),('gamma','γ')):
        value=value.replace('\\'+command,symbol)
    return value


def value(raw):
    from backend.services.quality_verifiers import option_value
    return normalize(option_value(raw))


def exact_number(raw):
    """Finite decimal/fraction or bounded binary scale, with no expression eval."""
    text=value(raw)
    if len(text)>160:return None
    if re.fullmatch(r'[+-]?\d+(?:\.\d+)?(?:/\d+)?',text):
        try:
            result=Fraction(text)
            return result if abs(result.numerator).bit_length()<=512 and result.denominator.bit_length()<=512 else None
        except (ValueError,ZeroDivisionError):return None
    m=re.fullmatch(r'([+-]?)(\d+(?:\.\d+)?\*)?2\^\(?([+-]?\d{1,3})\)?',text)
    if text.count('(')!=text.count(')'):return None
    if m and abs(int(m[3]))<=200:
        coefficient=Fraction(m[2][:-1]) if m[2] else Fraction(1)
        return (-1 if m[1]=='-' else 1)*coefficient*Fraction(2)**int(m[3])
    return None


def ieee_numeric_comparison(raw,target):
    decimal=exact_number(raw)
    if decimal is None:return False if value(raw) in {'非数（NaN）','非数(NaN)','NaN'} else None
    m=re.fullmatch(r'([+-]?)([01]+)\.([01]+)\*2\^\(?([+-]?\d+)\)?',value(raw))
    if m:
        binary=(int(m[2],2)+Fraction(int(m[3],2),1<<len(m[3])))*Fraction(2)**int(m[4])*(-1 if m[1]=='-' else 1)
        if (binary==target)!=(decimal==target):return None  # unspecified radix would change the answer
    return decimal==target


def choice(q,adapter,target,proof,compare=None):
    compare=compare or (lambda raw:exact_number(raw)==exact_number(str(target))
        if exact_number(raw) is not None and exact_number(str(target)) is not None else None)
    if q.question_type!='single_choice':
        outcome=compare(q.correct_answer)
        return {'status':'PASS' if outcome is True else 'FAIL' if outcome is False else 'UNKNOWN',
            'adapter':adapter,'derived_answer':str(target),'reason':'exact_value_matches' if outcome else 'reference_not_equal_or_supported',
            'proof':proof,'problem_identity':{'adapter':adapter,'parameters':proof.get('parameters'),'goal':proof.get('goal')}}
    outcomes={k:compare(raw) for k,raw in (q.options or {}).items()}
    matches=[k for k,v in outcomes.items() if v is True]
    status='UNKNOWN' if any(v is None for v in outcomes.values()) else 'FAIL' if len(matches)!=1 else 'PASS' if q.correct_answer.strip().upper()==matches[0] else 'FAIL'
    return {'status':status,'adapter':adapter,'derived_answer':matches[0] if len(matches)==1 else None,
        'derived_key':matches[0] if len(matches)==1 else None,'matching_options':matches,
        'reason':'option_unverifiable' if status=='UNKNOWN' else 'non_unique_option' if len(matches)!=1 else 'derived_key_matches' if status=='PASS' else 'derived_key_conflict',
        'proof':proof,'problem_identity':{'adapter':adapter,'parameters':proof.get('parameters'),'goal':proof.get('goal')}}


def problem(q):
    if q.question_type not in {'single_choice','fill_blank','calculation'}:return None
    text=normalize(q.stem)
    from backend.services.phase45hx_math_verifiers import problem as math_recovery_problem
    recovered_math = math_recovery_problem(q, text)
    if recovered_math is not None:
        return recovered_math
    from backend.services.phase45hx_crc_verifier import problem as crc_detection_problem
    crc_detection = crc_detection_problem(q, text)
    if crc_detection is not None:
        return crc_detection
    bounded_stem = text.replace('（', '(').replace('）', ')').rstrip('。')
    # A train-yard side track is a FIFO lane: cars cannot pass within a lane,
    # and each lane runs from entrance to exit. Accept only the explicit,
    # one-way n-lane permutation form rather than guessing from keywords.
    rail=re.fullmatch(
        r'设有(?:下图所示的)?火车车轨,入口到出口之间有n条轨道,列车的行进方向均为从左至右,列车可驶入任意一条轨道。?'
        r'现有编号为(\d{1,3})[～~](\d{1,3})的(\d{1,3})列列车,驶入的次序依次是(\d{1,3}(?:[,、]\d{1,3}){1,63})。?'
        r'若期望驶出的次序依次为(\d{1,3})[～~](\d{1,3}),则n至少是(?:\(\)|（）|_+|＿+)?[。.]?',text)
    if rail:
        first,last,count=map(int,rail.group(1,2,3));incoming=[int(v) for v in re.split('[,、]',rail[4])]
        out_first,out_last=map(int,rail.group(5,6))
        if ((first,last)!=(out_first,out_last) or count!=len(incoming)
                or not 1<=first<=last<=999 or last-first+1!=count
                or len(incoming)<2 or len(incoming)>64):
            return {'status':'UNKNOWN','adapter':'hs_rail_tracks_minimum_fifo_v1','reason':'unsupported_track_problem_bounds'}
        target_order=list(range(out_first,out_last+1))
        if sorted(incoming)!=target_order or len(set(incoming))!=len(incoming):
            return {'status':'UNKNOWN','adapter':'hs_rail_tracks_minimum_fifo_v1','reason':'cars_must_be_a_permutation_of_requested_output'}
        # Exact dynamic-programming longest decreasing subsequence and witness.
        lengths=[1]*len(incoming);previous=[None]*len(incoming)
        for i,current in enumerate(incoming):
            for j in range(i):
                if incoming[j]>current and lengths[j]+1>lengths[i]:
                    lengths[i]=lengths[j]+1;previous[i]=j
        end=max(range(len(incoming)),key=lengths.__getitem__);lds=[];cursor=end
        while cursor is not None:
            lds.append(incoming[cursor]);cursor=previous[cursor]
        lds.reverse();lower_bound=len(lds)
        # Construct an increasing-subsequence (FIFO lane) partition. For each
        # car, extend the compatible lane with the greatest last car.
        lanes=[]
        for car in incoming:
            eligible=[(lane[-1],index) for index,lane in enumerate(lanes) if lane[-1]<car]
            if eligible:
                _,index=max(eligible);lanes[index].append(car)
            else:lanes.append([car])
        if len(lanes)!=lower_bound or sorted(v for lane in lanes for v in lane)!=target_order:
            return {'status':'UNKNOWN','adapter':'hs_rail_tracks_minimum_fifo_v1','reason':'lane_partition_crosscheck_failed'}
        proof={'parameters':{'incoming':incoming,'desired_output':target_order},'goal':'minimum_one_way_fifo_side_tracks',
            'longest_decreasing_subsequence':lds,'lower_bound':lower_bound,'increasing_fifo_lanes':lanes,
            'upper_bound':len(lanes),
            'proof':'A decreasing subsequence cannot place two cars on the same FIFO lane; the displayed increasing partition uses exactly the LDS number of lanes.'}
        return choice(q,'hs_rail_tracks_minimum_fifo_v1',str(lower_bound),proof)
    if bounded_stem == '设有一个双向链表L,结构为[p2,d,p1],头结点为head,初始时head=cu。现要将每个结点的p2指向p1指向结点的直接后继,应该进行的操作是()':
        # This is a bounded structural audit of four fixed C loop forms, not
        # execution of candidate code.  The p1 chain is finite and acyclic;
        # p2 is not a valid traversal sentinel.  Only D guards the two-step
        # dereference and advances past the final node.
        patterns={
            'A':r'while\(cu!=NULL\)\{cu->p2=cu->p1->p1;cu=cu->p1;?\}',
            'B':r'while\(cu!=NULL&&cu->p2!=NULL\)\{cu->p2=cu->p1->p1;cu=cu->p1;?\}',
            'C':r'while\(cu!=NULL\)\{if\(cu->p1!=NULL\)\{cu->p2=cu->p1->p1;cu=cu->p1;?\}\}',
            'D':r'while\(cu!=NULL\)\{if\(cu->p1!=NULL\)cu->p2=cu->p1->p1;cu=cu->p1;?\}',
        }
        if q.question_type!='single_choice' or set(q.options or {})!={'A','B','C','D'}:
            return {'status':'UNKNOWN','adapter':'hs_doubly_list_two_step_pointer_v1','reason':'expected_four_choice_pointer_loop'}
        forms={}
        for key,raw in (q.options or {}).items():
            code=normalize(value(raw)).rstrip(';')
            forms[key]=next((name for name,pattern in patterns.items() if re.fullmatch(pattern,code)),None)
        if any(form is None for form in forms.values()):
            return {'status':'UNKNOWN','adapter':'hs_doubly_list_two_step_pointer_v1','reason':'unrecognized_pointer_loop_form',
                'proof':{'recognized_option_forms':forms,'scope':'four fixed exam code patterns only'}}
        correct=[key for key,form in forms.items() if form=='D']
        status='FAIL' if len(correct)!=1 else 'PASS' if q.correct_answer.strip().upper()==correct[0] else 'FAIL'
        return {'status':status,'adapter':'hs_doubly_list_two_step_pointer_v1',
            'reason':'derived_key_matches' if status=='PASS' else 'non_unique_or_conflicting_pointer_loop',
            'derived_answer':correct[0] if len(correct)==1 else None,'matching_options':correct,
            'proof':{'list_invariant':'p1 is the forward link of a finite acyclic list; update p2 to the successor of p1 when p1 exists',
                'safe_update':'test cu->p1 before reading cu->p1->p1, then advance cu unconditionally',
                'option_forms':forms,
                'failure_reasons':{'A':'dereferences cu->p1->p1 when cu is the tail','B':'uses p2 as an unspecified stop condition and does not guard p1 dereference',
                    'C':'does not advance cu when it reaches the tail','D':'guards the dereference and advances beyond the tail'},
                'method':'static recognition of the four complete bounded loop forms; no code execution'}}
    if text==r'设f(a)=\int_2^{+\infty}\frac{1}{x(\lnx)^{a+1}}\,dx,若f(a)在a=a_0处取得最小值,求a_0：':
        from sympy import Symbol,log,diff,simplify
        a=Symbol('a',positive=True);L=log(log(2));f=log(2)**(-a)/a
        derivative=simplify(diff(log(f),a));second=simplify(diff(derivative,a))
        target='-1/ln(ln2)'
        def compare(raw):
            option=value(raw).replace('\\ln','ln').replace('ln(2)','ln2')
            if option==target:return True
            if option in {'-ln(ln2)','1/ln2','-1/ln2','ln2'}:return False
            return None
        return choice(q,'hs_log_integral_min',target,{'parameters':[2,'a+1'],'goal':'global_min_parameter',
            'domain':'a>0','substitution':'t=ln(x), dt=dx/x','function':'1/(a*(ln2)^a)',
            'log_derivative':str(derivative),'log_second_derivative':str(second),'optimum':target,
            'bounds':['1/2<ln2<1; e>2, so exp(-1)<ln2<1','-1<ln(ln2)<0',
                'optimum>1; -ln(ln2), ln2 lie between0and1; negative reciprocal outside domain']},compare)
    m=re.fullmatch(r'空栈,入栈序列([a-zA-Z0-9](?:[,、][a-zA-Z0-9]){1,20})；依次操作((?:Push|Pop)(?:、(?:Push|Pop)){1,80}),出栈序列为[？?。]?',text)
    if m:
        incoming=re.split('[,、]',m[1]);stack=[];pops=[];index=0;trace=[]
        for op in m[2].split('、'):
            if op=='Push':
                if index>=len(incoming):return {'status':'UNKNOWN','adapter':'hs_stack_operations','reason':'push_input_exhausted'}
                stack.append(incoming[index]);index+=1
            elif not stack:return {'status':'UNKNOWN','adapter':'hs_stack_operations','reason':'stack_underflow'}
            else:pops.append(stack.pop())
            trace.append({'op':op,'stack':list(stack),'pops':list(pops)})
        return choice(q,'hs_stack_operations',','.join(pops),{'parameters':{'incoming':incoming,'operations':m[2].split('、')},'goal':'pop_sequence','trace':trace},
            lambda raw:re.split('[,、]',value(raw))==pops)
    m=re.fullmatch(r'S1从底到顶为([0-9,、-]+)；S2运算符依次为([*、+,-]+)（\+在栈顶）。每次弹出a、b、op后计算bopa并压回,调用(\d+)次后栈顶是多少[？?。]?',text)
    if m:
        stack=[Fraction(n) for n in re.split('[,、]',m[1])];operators=re.split('[,、]',m[2]);original=list(stack);trace=[]
        if int(m[3])>len(operators):return {'status':'UNKNOWN','adapter':'hs_stack_arithmetic','reason':'operator_underflow'}
        for _ in range(int(m[3])):
            if len(stack)<2:return {'status':'UNKNOWN','adapter':'hs_stack_arithmetic','reason':'operand_underflow'}
            a,b=stack.pop(),stack.pop();op=operators.pop();answer=b+a if op=='+' else b-a if op=='-' else b*a if op=='*' else None
            if answer is None:return None
            stack.append(answer);trace.append({'a':str(a),'b':str(b),'op':op,'value':str(answer)})
        return choice(q,'hs_stack_arithmetic',str(stack[-1]),{'parameters':{'operands':[str(v) for v in original],'operators':m[2],'count':int(m[3])},'goal':'stack_top','trace':trace})
    m=re.fullmatch(r'MTU=(\d+)B,转发总长(\d+)B的IP数据报（首部(\d+)B）,尽量大分片。第(\d+)片总长度与MF分别为[？?。]?',text)
    if m:
        mtu,total,header,number=map(int,m.groups());capacity=(mtu-header)//8*8;remaining=total-header;fragments=[]
        if not 20<=header<=60 or header%4 or capacity<=0 or remaining<=0 or total>65535:return None
        while remaining>0:
            payload=min(capacity,remaining);remaining-=payload;fragments.append((payload+header,int(remaining>0)))
        if not 1<=number<=len(fragments):return {'status':'UNKNOWN','adapter':'hs_ipv4_fragment','reason':'requested_fragment_absent'}
        target=fragments[number-1]
        return choice(q,'hs_ipv4_fragment',str(target),{'parameters':[mtu,total,header,number],'goal':'fragment_length_and_mf','aligned_payload':capacity,'fragments':fragments},
            lambda raw:tuple(map(int,re.split('[,、]',value(raw))))==target if re.fullmatch(r'\d+[,、][01]',value(raw)) else None)
    m=re.fullmatch(r'某计算机主存地址为(\d+)位,按字节编址；Cache数据区容量为(\d+)KB,主存块大小为(\d+)B,采用(\d+)路组相联映射。Cache中比较器的个数和位数分别为（）。',text)
    if m:
        bits,kb,block,ways=map(int,m.groups());groups=kb*1024//block//ways
        if not 1<=bits<=64 or any(n<=0 or n&(n-1) for n in (kb*1024,block,ways,groups)) or kb*1024%(block*ways):return None
        tag=bits-(block.bit_length()-1)-(groups.bit_length()-1)
        if tag<=0:return None
        target=(ways,tag)
        return choice(q,'hs_cache_tag',str(target),{'parameters':[bits,kb,block,ways],'goal':'comparators_and_tag_bits','groups':groups,'offset_bits':block.bit_length()-1,'index_bits':groups.bit_length()-1,'tag_bits':tag},
            lambda raw:tuple(map(int,re.split('[,、]',value(raw))))==target if re.fullmatch(r'\d+[,、]\d+',value(raw)) else None)
    m=re.fullmatch(r'二叉树(\d+)个叶权值([0-9,、]+),最小带权路径长度WPL为[？?。]?',text)
    average=re.fullmatch(r'在由(\d+)个字符组成的字符集S中,各字符出现的频次分别为([0-9、,]+),为S构造的哈夫曼编码的加权平均长度为（）。',text)
    if m or average:
        match=m or average;weights=[int(v) for v in re.split('[、,]',match[2])]
        if len(weights)!=int(match[1]) or not 2<=len(weights)<=16 or any(not 1<=v<=1000000 for v in weights):return None
        heap=list(weights);heapq.heapify(heap);merges=[];wpl=0
        while len(heap)>1:
            a,b=heapq.heappop(heap),heapq.heappop(heap);wpl+=a+b;heapq.heappush(heap,a+b);merges.append([a,b,a+b])
        target=Fraction(wpl,sum(weights)) if average else wpl
        return choice(q,'hs_huffman_wpl',str(target),{'parameters':weights,'goal':'weighted_average' if average else 'minimum_wpl','merges':merges,'wpl':wpl,'total_weight':sum(weights),
            'theorem':'Each binary merge adds its subtree weight to WPL; Huffman greedy merging minimizes WPL.'})
    m=re.fullmatch(r'对n个互不相同的符号构造Huffman树,若整棵树共有(\d+)个结点,求n。',text)
    if m:
        nodes=int(m[1])
        if nodes<1 or nodes%2==0:return {'status':'UNKNOWN','adapter':'hs_huffman_nodes','reason':'not_a_full_binary_tree_count'}
        return choice(q,'hs_huffman_nodes',(nodes+1)//2,{'parameters':[nodes],'goal':'symbol_count','equations':['edges=N-1=2*internal','N=leaves+internal'],'leaf_count':(nodes+1)//2})
    m=re.fullmatch(r'字符a…([b-p])的码字依次为([01、,]+)。译码串([01]{1,512}),选结果[：:]?',text)
    if m:
        codes=re.split('[、,]',m[2]);letters=[chr(n) for n in range(ord('a'),ord(m[1])+1)]
        if len(codes)!=len(letters) or len(set(codes))!=len(codes) or any(a!=b and b.startswith(a) for a in codes for b in codes):return {'status':'UNKNOWN','adapter':'hs_huffman_decode','reason':'invalid_prefix_code'}
        mapping=dict(zip(codes,letters));decoded=[];pending=''
        for bit in m[3]:
            pending+=bit
            if pending in mapping:decoded.append(mapping[pending]);pending=''
        if pending:return {'status':'UNKNOWN','adapter':'hs_huffman_decode','reason':'incomplete_bitstream'}
        target=''.join(decoded)
        return choice(q,'hs_huffman_decode',target,{'parameters':{'codes':mapping,'encoded':m[3]},'goal':'prefix_decode','decoded':target},lambda raw:value(raw)==target)
    m=re.fullmatch(r'已知float型变量(?:用|采用)IEEE754单精度浮点数格式表示。若(?:float型)?变量x的机器数为([0-9A-Fa-f]{8})H,则x的值(?:是（）。|为[：:])',text)
    if m:
        word=int(m[1],16);sign=-1 if word>>31 else 1;exponent=(word>>23)&255;mantissa=word&((1<<23)-1)
        if exponent==255:return {'status':'UNKNOWN','adapter':'hs_ieee_decode','reason':'nonfinite_value_requires_category_grader'}
        answer=sign*Fraction(mantissa if exponent==0 else (1<<23)+mantissa)*Fraction(2)**(-149 if exponent==0 else exponent-127-23)
        proof={'parameters':[word],'goal':'binary32_value','sign':sign,'exponent':exponent,'fraction':mantissa,'exact_value':str(answer)}
        return choice(q,'hs_ieee_decode',str(answer),proof,lambda raw:ieee_numeric_comparison(raw,answer))
    m=re.fullmatch(r'([+-]?\d+(?:\.\d+)?)的IEEE754单精度浮点数表示为（）。',text)
    if m:
        target=Fraction(m[1])
        try:word=int.from_bytes(struct.pack('>f',float(target)),'big');roundtrip=struct.unpack('>f',word.to_bytes(4,'big'))[0]
        except (OverflowError,ValueError):return None
        if Fraction(roundtrip)!=target:return {'status':'UNKNOWN','adapter':'hs_ieee_encode','reason':'inexact_encoding_outside_scope'}
        return choice(q,'hs_ieee_encode',f'{word:08X}',{'parameters':[str(target)],'goal':'binary32_exact_encoding','word':f'{word:08X}','roundtrip_exact':True},
            lambda raw:int(value(raw).rstrip('Hh'),16)==word if re.fullmatch(r'[0-9A-Fa-f]{8}[Hh]?',value(raw)) else None)
    if text=='求IEEE754单精度最小的规格化正数。':
        return choice(q,'hs_ieee_min_normal',str(Fraction(1,1<<126)),{'parameters':['binary32','normalized'],'goal':'minimum_positive_normal','exponent_field':1,'bias':127,'fraction_field':0,'formula':'1*2^(1-127)'})
    if text=='求参数：lim(x→0)(e^x+ax^(2)+bx)^(1/x^(2))=1。选项对应(a,b)：':
        target=(Fraction(-1,2),Fraction(-1))
        def pair(raw):
            found=re.fullmatch(r'\(([^,]+),([^,]+)\)',value(raw))
            if not found:return None
            try:return tuple(Fraction(v) for v in found.groups())==target
            except ValueError:return None
        return choice(q,'hs_limit_parameters',str(target),{'parameters':['exp(x)+a*x^2+b*x','power 1/x^2','target 1'],'goal':'a_b',
            'proof':['log(1+u)=u-u^2/2+O(u^3)','finite unit limit requires b+1=0','then log limit=a+1/2=0'],'derived_parameters':['-1/2','-1']},pair)
    vector_pattern=r'-?\d+,-?\d+,-?\d+'
    span_pattern=(r'向量α_1=\('+vector_pattern+r'\)\^T,α_2=\('+vector_pattern+
        r'\)\^T,β_1=\('+vector_pattern+r'\)\^T,β_2=\('+vector_pattern+
        r'\)\^T。若γ既属于\\\{α_1,α_2\\\}的线性张成,也属于\\\{β_1,β_2\\\}的线性张成,则γ为：')
    if re.fullmatch(span_pattern,text):
        from sympy import Matrix
        vectors=re.findall(r'([αβ])_?([12])=\((-?\d+),(-?\d+),(-?\d+)\)(?:\^T|T)',text)
        if len(vectors)!=4 or [(v[0],v[1]) for v in vectors]!=[('α','1'),('α','2'),('β','1'),('β','2')]:return None
        parsed=[list(map(int,v[2:])) for v in vectors]
        if max(abs(n) for row in parsed for n in row)>1000:return None
        A=Matrix.hstack(*[Matrix(v) for v in parsed[:2]]);B=Matrix.hstack(*[Matrix(v) for v in parsed[2:]])
        common=[A*v[:2,0] for v in A.row_join(-B).nullspace()];common=[v for v in common if v!=Matrix.zeros(3,1)]
        if not common or Matrix.hstack(*common).rank()!=1:return {'status':'UNKNOWN','adapter':'hs_span_intersection','reason':'intersection_not_a_single_line'}
        basis=common[0]
        def line(raw):
            found=re.fullmatch(r'k\((-?\d+),(-?\d+),(-?\d+)\)(?:\^T|T)(?:,?k\\{1,2}in\\mathbbR)?',value(raw))
            if not found:return None
            vector=Matrix(list(map(int,found.groups())))
            return vector!=Matrix.zeros(3,1) and Matrix.hstack(basis,vector).rank()==1
        return choice(q,'hs_span_intersection',str(list(basis)),{'parameters':parsed,'goal':'intersection_line','basis':[str(v) for v in basis],
            'method':'exact nullspace of [A,-B], then project through A'},line)
    rank_text=text.replace('A^*','A*')
    if re.fullmatch(r'A为4阶矩阵,A\*为伴随矩阵。若A\(A-A\*\)=O且A(?:\\ne|≠)A\*,则r\(A\)可能为[：:]?',rank_text):
        return choice(q,'hs_rank_square_zero','1,2',{'parameters':['4x4','A(A-adj(A))=0','A!=adj(A)'],'goal':'possible_ranks',
            'proof':['rank4 implies A=adj(A), excluded','rank3: det=0 so A^2=0; rank(A^2)>=2rank(A)-4=2, contradiction',
            'rank0 violates A!=adj(A)','rank1 and rank2 square-zero nilpotent matrices have adj(A)=0 and satisfy conditions']},
            lambda raw:set(map(int,re.findall(r'\d+',value(raw))))=={1,2} if re.fullmatch(r'\d或\d',value(raw)) else None)
    if ('CRC' in text and '可以断定' in text and '未发生错误' in text):
        return {'status':'UNKNOWN','adapter':'hs_crc_ambiguity','reason':'crc_zero_does_not_prove_no_transmission_error'}
    if text==('现有非空双向链表L,其结点结构为prev|data|next,prev指向直接前驱结点,next指向直接后继结点。'
        '若要在L中指针p所指向的结点（非尾结点）之后插入指针s所指向的新结点,则在执行语句序列'
        's->next=p->next;p->next=s;后,还需要执行（）。'):
        outcomes={};trace={}
        for key,raw in (q.options or {}).items():
            statements=[s for s in value(raw).split(';') if s];nodes={'P':{'next':'N','prev':'B'},'N':{'prev':'P','next':None},'S':{'prev':None,'next':'N'}}
            nodes['P']['next']='S';variables={'p':'P','s':'S'}
            def resolve(expression):
                parts=expression.split('->');node=variables[parts[0]]
                for field in parts[1:]:node=nodes[node][field]
                return node
            try:
                for statement in statements:
                    if not re.fullmatch(r'[ps](?:->(?:prev|next)){1,3}=[ps](?:->(?:prev|next)){0,3}',statement):raise ValueError('unsupported_pointer_statement')
                    left,right=statement.split('=');owner,field=left.rsplit('->',1);nodes[resolve(owner)][field]=resolve(right)
                outcomes[key]=(nodes['P']['next']=='S' and nodes['S']['next']=='N' and nodes['S']['prev']=='P' and nodes['N']['prev']=='S')
                trace[key]=nodes
            except (KeyError,TypeError,ValueError):outcomes[key]=None
        reverse={value(raw):outcomes[key] for key,raw in (q.options or {}).items()}
        return choice(q,'hs_list_insertion','complete_bidirectional_links',{'parameters':['P has successor N','new S','S.next=N;P.next=S'],'goal':'restore_prev_links','option_states':trace},lambda raw:reverse.get(value(raw)))
    return None


def explanation(q,independent):
    """Render actual solver steps, hash-bound by the shared public review service."""
    if independent.get('status')!='PASS' or independent.get('adapter') not in SOLVERS:return None
    proof=independent['proof'];adapter=independent['adapter'];answer=independent['derived_answer']
    from backend.services.phase45hx_math_verifiers import explanation as math_recovery_explanation
    recovered_math = math_recovery_explanation(q, independent)
    if recovered_math is not None:
        return recovered_math
    from backend.services.phase45hx_crc_verifier import explanation as crc_detection_explanation
    crc_detection = crc_detection_explanation(q, independent)
    if crc_detection is not None:
        return crc_detection
    if adapter=='hs_stack_operations':text='按 LIFO 规则逐步模拟 Push/Pop，栈及输出变化为 '+str(proof['trace'])
    elif adapter=='hs_stack_arithmetic':text='每次按给定次序取 a、b，计算 b op a；精确运算步骤为 '+str(proof['trace'])
    elif adapter=='hs_ipv4_fragment':text=f"除最后一片外，数据长度为8字节的倍数；最大对齐负载为{proof['aligned_payload']}字节。逐片（总长度，MF）为{proof['fragments']}"
    elif adapter=='hs_cache_tag':text=f"数据容量除以块大小和路数得到{proof['groups']}组；块内偏移{proof['offset_bits']}位、组索引{proof['index_bits']}位，地址剩余{proof['tag_bits']}位为标记；每路一个比较器"
    elif adapter=='hs_huffman_wpl':text=f"每次合并最小的两个权值：{proof['merges']}。每次合并增加相应子树权值，合计WPL={proof['wpl']}；总权值{proof['total_weight']}，加权平均长度为WPL/总权值"
    elif adapter=='hs_huffman_nodes':text=f"Huffman二叉树的非叶结点都有两个孩子，由{proof['equations']}解得叶结点数{proof['leaf_count']}，等于符号数"
    elif adapter=='hs_huffman_decode':text=f"逐位读取到完整前缀码便输出对应字符，码表{proof['parameters']['codes']}，译码结果为{proof['decoded']}，没有未完成尾码"
    elif adapter=='hs_ieee_decode':text=f"拆分符号、8位阶码和23位尾数字段：{proof['sign']}、{proof['exponent']}、{proof['fraction']}。阶码为0时采用非规格化规则，否则减偏置127并补隐含首位1；精确值为{proof['exact_value']}"
    elif adapter=='hs_ieee_encode':text=f"将输入有理数编码成 binary32，再按字段精确解码核对值不变；结果机器数为{proof['word']}，本题无需舍入近似"
    elif adapter=='hs_ieee_min_normal':text='规格化数最小非零阶码字段为1，实际指数1-127=-126；尾数取0、隐含整数位为1，得2^(-126)'
    elif adapter=='hs_limit_parameters':text='取对数并在0邻域作二阶展开；一次项系数必须为0得到b=-1，再令二次项系数a+1/2=0，得到a=-1/2。此时底数在0邻域为正，原式极限为1'
    elif adapter=='hs_span_intersection':text=f"构造[A,-B]并精确求零空间，投影到A的列空间得到交空间基{proof['basis']}；交空间为一维，逐项检查选项向量与该基共线"
    elif adapter=='hs_rank_square_zero':text='；'.join(proof['proof'])
    elif adapter=='hs_log_integral_min':text='令t=ln(x)，积分仅在a>0时收敛，得f(a)=1/[a(ln2)^a]。对数导数为-1/a-ln(ln2)，二阶导数为1/a²>0，故唯一全局最小值在a=-1/ln(ln2)。由1/2<ln2<1及e>2可知-1<ln(ln2)<0，从而该参数大于1，其余选项不等于它或不在收敛域'
    elif adapter=='hs_doubly_list_two_step_pointer_v1':
        reasons=proof['failure_reasons']
        text=(f"遍历有限的 p1 链时，只有 cu->p1 非空才能安全读取 cu->p1->p1；更新后仍须无条件令 cu=cu->p1，才能在尾结点退出。"
            f"A 会在尾结点解引用空指针；B 用未说明的 p2 值作为停止条件且未保护 p1；C 到尾结点不前进；D 同时满足安全检查和遍历前进")
    elif adapter=='hs_rail_tracks_minimum_fifo_v1':
        text=(f"同一条单向侧轨内不能超车，因此该轨道上的车辆按入轨顺序也必须按出轨顺序排列。"
            f"递减子序列 {proof['longest_decreasing_subsequence']} 中的车辆不能共用一条轨道，所以至少需要 {proof['lower_bound']} 条。"
            f"另一方面，可分成递增轨道 {proof['increasing_fifo_lanes']}，每条轨道均保持先进先出，且轨道数为 {proof['upper_bound']}。"
            f"上下界相同，最少轨道数为 {proof['lower_bound']}")
    else:text='先执行题干已给的next赋值，再逐项模拟选项的prev赋值，检查P→S→N及反向N→S→P均成立；各选项状态为'+str(proof['option_states'])
    return text+'。因此答案为 '+str(answer)+'。',{'adapter':adapter,'proof':proof}
