#!/usr/bin/python
import re, sys, os
from cllparser import *

optable = { 
    '+': 'ADD',
    '-': 'SUB',
    '*': 'MUL',
    '/': 'DIV',
    '^': 'EXP',
    '%': 'MOD',
    '#/': 'SDIV',
    '#%': 'SMOD',
    '==': 'EQ',
    '<=': 'LE',
    '>=': 'GE',
    '<': 'LT',
    '>': 'GT'
}

funtable = {
    'sha256': ['SHA256', 3],
    'sha3': ['SHA3', 3],
    'ripemd160': ['RIPEMD160', 3],
    'ecsign': ['ECSIGN', 2],
    'ecrecover': ['ECRECOVER', 4],
    'ecvalid': ['ECVALID', 2],
    'ecadd': ['ECADD', 4],
    'ecmul': ['ECMUL', 3],
}

pseudovars = {
    'tx.datan': 'TXDATAN',
    'tx.sender': 'TXSENDER',
    'tx.value': 'TXVALUE',
    'block.timestamp': 'BLK_TIMESTAMP',
    'block.number': 'BLK_NUMBER',
    'block.basefee': 'BASEFEE',
    'block.difficulty': 'BLK_DIFFICULTY',
    'block.coinbase': 'BLK_COINBASE',
    'block.parenthash': 'BLK_PREVHASH'
}

pseudoarrays = {
    'tx.data': 'TXDATA',
    'contract.storage': 'SLOAD',
    'block.address_balance': 'BALANCE',
}

# Left-expressions can either be:
# * variables
# * A[B] where A is a left-expr and B is a right-expr
# * contract.storage[B] where B is a right-expr
def get_left_expr_type(expr):
    if isinstance(expr,str):
        return 'variable'
    elif expr[0] == 'access' and expr[1] == 'contract.storage':
        return 'storage'
    else:
        return 'access'

def compile_left_expr(expr,varhash):
    typ = get_left_expr_type(expr)
    if typ == 'variable':
        if re.match('^[0-9\-]*$',expr):
            raise Exception("Can't set the value of a number! "+expr)
        elif expr in varhash:
            return ['PUSH',varhash[expr]]
        else:
            varhash[expr] = len(varhash)
            return ['PUSH',varhash[expr]]
    elif typ == 'storage':
        return compile_expr(expr[2],varhash)
    elif typ == 'access':
        if get_left_expr_type(expr[1]) == 'storage':
            return compile_left_expr(expr[1],varhash) + ['SLOAD'] + compile_expr(expr[2],varhash)
        else:
            return compile_left_expr(expr[1],varhash) + compile_expr(expr[2],varhash) + ['ADD']
    else:
        raise Exception("invalid op: "+expr[0])

# Right-hand-side expressions (ie. the normal kind)
def compile_expr(expr,varhash,functionhash={},lc=[0]):
    if isinstance(expr,str):
        if re.match('^[0-9\-]*$',expr):
            return ['PUSH',int(expr)]
        elif re.match('^REF_',expr):
            return [expr]
        elif expr in varhash:
            return ['PUSH',varhash[expr],'MLOAD']
        elif expr in pseudovars:
            return [pseudovars[expr]]
        else:
            varhash[expr] = len(varhash)
            return ['PUSH',varhash[expr],'MLOAD']
    elif expr[0] in optable:
        if len(expr) != 3:
            raise Exception("Wrong number of arguments: "+str(expr))
        f = compile_expr(expr[1],varhash)
        g = compile_expr(expr[2],varhash)
        return g + f + [optable[expr[0]]]
    elif expr[0] == 'fun' and expr[1] in funtable:
        if len(expr) != funtable[expr[1]][1] + 2:
            raise Exception("Wrong number of arguments: "+str(expr)) 
        f = sum([compile_expr(e,varhash) for e in expr[2:]],[])
        return f + [funtable[expr[1]][0]]
    elif expr[0] == 'access':
        if expr[1][0] == 'block.contract_storage':
            return compile_expr(expr[2],varhash) + compile_expr(expr[1][1],varhash) + ['EXTRO']
        elif expr[1] in pseudoarrays:
            return compile_expr(expr[2],varhash) + [pseudoarrays[expr[1]]]
        else:
            return compile_left_expr(expr[1],varhash) + compile_expr(expr[2],varhash) + ['ADD','MLOAD']
    elif expr[0] == 'fun' and expr[1] == 'array':
        return [ 'PUSH', 0, 'PUSH', 1, 'SUB', 'MLOAD', 'PUSH',
                         2, 'PUSH', 160, 'EXP', 'ADD', 'DUP',
                         'PUSH', 0, 'PUSH', 1, 'SUB', 'MSTORE' ]
    elif expr[0] == 'fun':
        #!bang
        if expr[1] not in functionhash:
            raise Exception("function not defined: "+expr[1])
        # That's a custom function.
        print "\n\n\n!trace d -------------- custom function?"
        # So what we want to do push the return value.
        print "functionhash? ", functionhash
        print "expr: ", expr
        # Go -> Return -> Set
        # Setup our return point.
        print "show me the LC! ---------> ", lc
        label, ref = 'LABEL_'+str(lc[0]), 'REF_'+str(lc[0])
        # increment it.
        lc[0] += 1
        # Save that in the variable reserved for this function.
        funcreturnstmt = ['set',expr[1] + "_returnpoint",ref]
        print "ret statement: ", funcreturnstmt
        functionreturn = compile_stmt(funcreturnstmt,varhash,functionhash,lc)
        print "our function return: ", functionreturn
        # Set each variable which represents a parameter for the function.
        params = []
        paramidx = -1
        for ex in expr[2:]:
            paramidx += 1
            setparamstmt = ['set',functionhash[expr[1]]['params'][paramidx],ex]
            print "new setparamstmt: ", setparamstmt
            for part in compile_stmt(setparamstmt,varhash,functionhash,lc): params.append(part)

        # thereturn = expr[2:]
        # Ok, you should be able to put that together now.
        # Steps again:
        # - Set function return variable
        # - Set parameters
        # - Go to the function
        # - Set the label
        thereturn = functionreturn + params + [ functionhash[expr[1]]['funcref'], 'JMP' ] + [ label ] + [ 'SWAP' ]
        print "THERETURN: ", thereturn
        print "params: ", params
        print varhash
        print "\n\n\n\n"
        return thereturn


    elif expr[0] == '!':
        f = compile_expr(expr[1],varhash)
        return f + ['NOT']
    elif expr[0] in pseudoarrays:
        return compile_expr(expr[1],varhash) + pseudoarrays[expr[0]]
    elif expr[0] in ['or', '||']:
        return compile_expr(['!', [ '*', ['!', expr[1] ], ['!', expr[2] ] ] ],varhash)
    elif expr[0] in ['and', '&&']: 
        return compile_expr(['!', [ '+', ['!', expr[1] ], ['!', expr[2] ] ] ],varhash)
    elif expr[0] == 'multi':
        return sum([compile_expr(e,varhash) for e in expr[1:]],[])
    elif expr == 'tx.datan':
        return ['DATAN']
    else:
        raise Exception("invalid op: "+expr[0])

# Statements (ie. if, while, a = b, a,b,c = d,e,f, [ s1, s2, s3 ], stop, suicide)
def compile_stmt(stmt,varhash={},functionhash={},lc=[0],endifmarker=[0],endifknown=[0]):
    if stmt[0] in ['if', 'elif', 'else']:
        # Typically we use the second index, which is the condition for the if
        stmtindex = 2
        # However, with else, our condition isn't explicit.
        if stmt[0] == "else":
            # So we use a previous index in this statement
            stmtindex = 1
            # Set that we know the endif exists, at this label.
            endifmarker[0] = lc[0]
            endifknown[0] = 1
        else:
            # Additionally we compile expressions only for conditionals.
            f = compile_expr(stmt[1],varhash,functionhash,lc)
        g = compile_stmt(stmt[stmtindex],varhash,functionhash,lc,endifmarker,endifknown)
        h = compile_stmt(stmt[3],varhash,functionhash,lc,endifmarker,endifknown) if len(stmt) > 3 else None
        label, ref = 'LABEL_'+str(lc[0]), 'REF_'+str(lc[0])
        # We hold the lc's place, as if the end if location is unknown this "could be end if"
        couldbeendif = lc[0]
        lc[0] += 1
        if stmt[0] == "else": return g + [ label ]
        else:
            if not endifknown[0]:
                # If our endif is unknown, we mark it here
                endifmarker[0] = couldbeendif
                endifknown[0] = 1
            # An if denotes the beginning of a if/elif/else block, reset our known endif
            if stmt[0] == "if": endifknown[0] = 0
            if h: return f + [ 'NOT', ref, 'SWAP', 'JMPI' ] + g + [ 'REF_'+str(endifmarker[0]), 'JMP' ] + [ label ] + h
            else: return f + [ 'NOT', ref, 'SWAP', 'JMPI' ] + g + [ label ]
    elif stmt[0] == "def":
        print "!trace >>>>>>>>>>>>>------------->>>>>>>>>>>>>>>>>>>>"
        print "statement: ", stmt
        print "varhash: ", varhash
        print "label collection: ", lc
        # create the reference and label.
        label, ref = 'LABEL_'+str(lc[0]), 'REF_'+str(lc[0])
        # increment it.
        lc[0] += 1
        # hey, we're going to need a label INSIDE, so we can access this.
        insidelabel, insideref = 'LABEL_'+str(lc[0]), 'REF_'+str(lc[0])
        lc[0] += 1
        # Compile our sequence
        print "our sequence: ", stmt[2]
        f = compile_stmt(stmt[2],varhash,functionhash,lc)
        print "!tracer round **********************************"
        print "varhash: ", varhash
        # we'll need a few vars? 
        # namely: the functionhash
        # let's init that.
        funcname = stmt[1][1]
        functionhash[funcname] = {}
        functionhash[funcname]['params'] = []
        functionhash[funcname]['funcref'] = insideref
        # - one of which is: where do we go at the end, we return to whence we came.
        # we need this every time, let's make it.
        varhash[funcname + '_returnpoint'] = len(varhash)

        # - another of which is: the return value?
        #                             ^ maybe we just push that (we will)
        # - what about foreach parameter?
        # yep, gonna need that, let's add those.
        # hold on, we might not.
        # these should be used, and assigned.
        ###------------
        for param in stmt[1][2:]:
            print "param! ", param
            if param not in varhash:
                varhash[param] = len(varhash)
            functionhash[funcname]['params'].append(param)
        #    # return ['PUSH',varhash[expr],'MLOAD']
        print "modified functionhash: ", functionhash
        print "modified varhash: ", varhash
        thereturn = [ ref, 'JMP', insidelabel] + f + [ functionhash[funcname]['funcref'], 'JMP'] + [ label ]
        print thereturn
        return thereturn

    elif stmt[0] == 'while':
        f = compile_expr(stmt[1],varhash,functionhash,lc)
        g = compile_stmt(stmt[2],varhash,functionhash,lc)
        beglab, begref = 'LABEL_'+str(lc[0]), 'REF_'+str(lc[0])
        endlab, endref = 'LABEL_'+str(lc[0]+1), 'REF_'+str(lc[0]+1)
        lc[0] += 2
        return [ beglab ] + f + [ 'NOT', endref, 'SWAP', 'JMPI' ] + g + [ begref, 'JMP', endlab ]
    elif stmt[0] == 'set':
        lexp = compile_left_expr(stmt[1],varhash)
        rexp = compile_expr(stmt[2],varhash,functionhash,lc)
        lt = get_left_expr_type(stmt[1])
        return rexp + lexp + ['SSTORE' if lt == 'storage' else 'MSTORE']
    elif stmt[0] == 'mset':
        rexp = compile_expr(stmt[2],varhash,functionhash,lc)
        exprstates = [get_left_expr_type(e) for e in stmt[1][1:]]
        o = rexp
        for e in stmt[1][1:]:
            o += compile_left_expr(e,varhash)
            o += [ 'SSTORE' if get_left_expr_type(e) == 'storage' else 'MSTORE' ]
        return o
    elif stmt[0] == 'seq':
        o = []
        for s in stmt[1:]:
            o.extend(compile_stmt(s,varhash,functionhash,lc))
        return o
    elif stmt[0] == 'fun' and stmt[1] == 'mktx':
        to = compile_expr(stmt[2],varhash,functionhash,lc)
        value = compile_expr(stmt[3],varhash,functionhash,lc)
        datan = compile_expr(stmt[4],varhash,functionhash,lc)
        datastart = compile_expr(stmt[5],varhash,functionhash,lc)
        return datastart + datan + value + to + [ 'MKTX' ]
    elif stmt == 'stop':
        return [ 'STOP' ]
    elif stmt[0] == 'fun' and stmt[1] == 'suicide':
        return compile_expr(stmt[2]) + [ 'SUICIDE' ]
    elif stmt[0] == 'return':
        return compile_expr(stmt[1],varhash,functionhash,lc)
        
# Dereference labels
def assemble(c):
    print "THE BIG OLE: ", c, "\n\n\n"
    iq = [x for x in c]
    mq = []
    pos = 0
    labelmap = {}
    while len(iq):
        front = iq.pop(0)
        if isinstance(front,str) and front[:6] == 'LABEL_':
            labelmap[front[6:]] = pos
        else:
            mq.append(front)
            pos += 2 if isinstance(front,str) and front[:4] == 'REF_' else 1
    oq = []
    for m in mq:
        if isinstance(m,str) and m[:4] == 'REF_':
            oq.append('PUSH')
            oq.append(labelmap[m[4:]])
        else: oq.append(m)
    return oq

def compile(source):
    if isinstance(source,('str','unicode')): source = parse(source)
    #print p
    return assemble(compile_stmt(source))

if len(sys.argv) >= 2:
    if os.path.exists(sys.argv[1]):
        open(sys.argv[1]).read()
        print ' '.join([str(k) for k in compile(open(sys.argv[1]).read())])
    else:
        print ' '.join([str(k) for k in compile(sys.argv[1])])
