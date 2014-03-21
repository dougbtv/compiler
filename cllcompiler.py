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
    '>': 'GT',
    'and': 'AND',
    'or': 'OR',
    'xor': 'XOR',
    '&&': 'AND',
    '||': 'OR'
}

funtable = {
    'sha3': ['SHA3', 3, 1],
    'ecrecover': ['ECRECOVER', 4, 1],
    'byte': ['BYTE', 2, 1],
    'mkcall': ['CALL', 7, 1],
    'create': ['CREATE', 5, 1],
    'return': ['RETURN', 2, 0],
    'suicide': ['SUICIDE', 1, 0]
}

pseudovars = {
    'call.datasize': 'TXDATAN',
    'call.sender': 'TXSENDER',
    'call.value': 'CALLVALUE',
    'call.gasprice': 'GASPRICE',
    'call.origin': 'ORIGIN',
    'balance': 'BALANCE',
    'gas': 'GAS',
    'block.prevhash': 'BLK_PREVHASH',
    'block.coinbase': 'BLK_COINBASE',
    'block.timestamp': 'BLK_TIMESTAMP',
    'block.number': 'BLK_NUMBER',
    'block.difficulty': 'BLK_DIFFICULTY',
    'block.gaslimit': 'GASLIMIT',
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
            return compile_left_expr(expr[1],varhash) + compile_expr(expr[2],varhash) + ['PUSH',32,'MUL','ADD']
    else:
        raise Exception("invalid op: "+expr[0])

# Right-hand-side expressions (ie. the normal kind)
def compile_expr(expr,varhash):
    if isinstance(expr,str):
        if re.match('^[0-9\-]*$',expr):
            return ['PUSH',int(expr)]
        elif expr in varhash:
            return ['PUSH',varhash[expr],'MLOAD']
        elif expr in pseudovars:
            return [pseudovars[expr]]
        elif expr == 'tx.data':
            return ['PUSH','_TXDATALOC','MLOAD']
        else:
            varhash[expr] = len(varhash) * 32
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
    elif expr[0] == 'fun' and expr[1] == 'bytes':
        return compile_expr(expr[2],varhash) + ['MSIZE','SWAP','MSIZE','ADD','PUSH',1,'SUB','PUSH',0,'MSTORE8']
    elif expr[0] == 'fun' and expr[1] == 'array':
        return compile_expr(expr[2],varhash) + ['PUSH',32,'MUL','MSIZE','SWAP','MSIZE','ADD','PUSH',1,'SUB','PUSH',0,'MSTORE8']
    elif expr[0] == 'access':
        if expr[1] in pseudoarrays:
            return compile_expr(expr[2],varhash) + [pseudoarrays[expr[1]]]
        elif len(expr) == 3:
            return compile_left_expr(expr[1],varhash) + compile_expr(expr[2],varhash) + ['PUSH',32,'MUL','ADD','MLOAD']
        elif len(expr) == 4 and expr[3] == ':':
            return compile_left_expr(expr[1],varhash) + compile_expr(expr[2],varhash) + ['PUSH',32,'MUL','ADD']
        else:
            raise Exception("Weird parameters for array access")
    elif expr[0] == '!':
        f = compile_expr(expr[1],varhash)
        return f + ['NOT']
    elif expr[0] in pseudoarrays:
        return compile_expr(expr[1],varhash) + pseudoarrays[expr[0]]
    else:
        raise Exception("invalid op: "+expr[0])

# Statements (ie. if, while, a = b, a,b,c = d,e,f, [ s1, s2, s3 ], stop, suicide)
def compile_stmt(stmt,varhash={},lc=[0]):
    if stmt[0] == 'if':
        f = compile_expr(stmt[1],varhash)
        g = compile_stmt(stmt[2],varhash,lc)
        h = compile_stmt(stmt[3],varhash,lc) if len(stmt) > 3 else None
        label, ref = 'LABEL_'+str(lc[0]), 'REF_'+str(lc[0])
        lc[0] += 1
        if h: return f + [ 'NOT', ref, 'SWAP', 'JMPI' ] + g + [ ref, 'JMP' ] + h + [ label ]
        else: return f + [ 'NOT', ref, 'SWAP', 'JMPI' ] + g + [ label ]
    elif stmt[0] == 'while':
        f = compile_expr(stmt[1],varhash)
        g = compile_stmt(stmt[2],varhash,lc)
        beglab, begref = 'LABEL_'+str(lc[0]), 'REF_'+str(lc[0])
        endlab, endref = 'LABEL_'+str(lc[0]+1), 'REF_'+str(lc[0]+1)
        lc[0] += 2
        return [ beglab ] + f + [ 'NOT', endref, 'SWAP', 'JMPI' ] + g + [ begref, 'JMP', endlab ]
    elif stmt[0] == 'set':
        lexp = compile_left_expr(stmt[1],varhash)
        rexp = compile_expr(stmt[2],varhash)
        lt = get_left_expr_type(stmt[1])
        return rexp + lexp + ['SSTORE' if lt == 'storage' else 'MSTORE']
    elif stmt[0] == 'seq':
        o = []
        for s in stmt[1:]:
            o.extend(compile_stmt(s,varhash,lc))
        return o
    elif stmt == 'stop':
        return [ 'STOP' ]
    elif stmt[0] == 'fun' and stmt[1] in funtable:
        f = sum([compile_expr(e,varhash) for e in stmt[2:]],[])
        if len(stmt) != funtable[stmt[1]][1] + 2:
            raise Exception("Wrong number of arguments: "+str(stmt)) 
        o = f + [funtable[stmt[1]][0]]
        if stmt[1][2] == 0:
            o += ['POP']
        return o

def get_vars(thing,h={}):
    if thing[0] in ['seq','if','while','set','access']:
        for t in thing[1:]: h = get_vars(t,h)
    elif thing[0] == 'fun':
        for t in thing[2:]: h = get_vars(t,h)
    elif isinstance(thing,(str,unicode)) and thing not in pseudovars and thing not in pseudoarrays:
        h[thing] = true
    return h
        
# Dereference labels
def assemble(c,varcount=99):
    iq = [x for x in c]
    mq = []
    pos = 0
    labelmap = {}
    if '_TXDATALOC' in mq:   
        mq = ['PUSH',varcount*32,'DUP','CALLDATA'] + mq
    while len(iq):
        front = iq.pop(0)
        if isinstance(front,str) and front[:6] == 'LABEL_':
            labelmap[front[6:]] = pos
        elif front == '_TXDATALOC':
            mq.apend(varcount*32)
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
    varhash = {}
    c = compile_stmt(source,varhash)
    return assemble(c,len(varhash))

if len(sys.argv) >= 2:
    if os.path.exists(sys.argv[1]):
        open(sys.argv[1]).read()
        print ' '.join([str(k) for k in compile(open(sys.argv[1]).read())])
    else:
        print ' '.join([str(k) for k in compile(sys.argv[1])])
