"""Performs local value numbering based optimizations"""

import json
import sys
from assignments.dce import dce
from assignments.form_blocks import form_blocks
from collections import defaultdict

def lvn(block):
    # maps 'value' cons into value number
    value_map = {}
    # indexed by value number, contains (value, canonical variable name)
    value_table = []

    # maps variable name to value number
    var2val = {}

    # rename variables to avoid conflicts later (essentially a local kind of SSA?). 
    # at the same time, find variables that are not defined within this basic block
    # and place them into value table 
    var_name_counts = defaultdict(int)
    for instr in block:
        # handle uses
        for i, arg in enumerate(instr.get('args', [])):
            if arg not in var_name_counts:
                # variable was not defined in this basic block
                # the actual value must be unique for each such case
                value = ('input', arg)
                value_number = len(value_table)
                value_map[value] = value_number
                value_table.append((value, arg))
                var2val[arg] = value_number
                var_name_counts[arg] += 1
            elif var_name_counts[arg] == 1:
                # there's only one definition of this so far, 
                # so we don't need to rename anything
                pass
            else:
                # there was at least 2 definitions of this so far,
                # we need to ensure arg is the latest name
                count = var_name_counts[arg]
                instr['args'][i] = f'{arg}__{count}'
        
        # handle def
        if 'dest' in instr:
            dest = instr['dest']
            var_name_counts[dest] += 1
            count = var_name_counts[dest]
            if count > 1:
                instr['dest'] = f'{dest}__{count}'

    # perform value numbering, rematerializing each instruction as we go along
    call_nonce = 0
    for instr in block:
        # if this instruction does not produce a value (i.e. it is an effect operation)
        # we just need to rewrite its arguments
        if 'dest' not in instr:
            if 'args' in instr:
                new_args = []
                for arg in instr['args']:
                    value_number = var2val[arg]
                    canonical_variable = value_table[value_number][1]
                    new_args.append(canonical_variable)
                instr['args'] = new_args
            continue

        # otherwise, we should see if the value it produces already exists in the table
        # note: function calls are not necessarily pure (they can include a print)
        # so we cannot really optimize them away by giving them value numbers
        if instr['op'] == 'call':
            value = (instr['op'], call_nonce)
            call_nonce += 1
        elif instr['op'] == 'const':
            # needed because python treats ints and bools kinda equivalently (why???)
            vtype = 'bconst' if isinstance(instr['value'], bool) else 'iconst'
            value = (vtype, instr['value'])
        else:
            value_numbers = [var2val[arg] for arg in instr['args']]

            # copy propagation - if value_number points to ('id', x), replace with just x
            value_numbers = [
                vn if value_table[vn][0][0] != 'id' else value_table[vn][0][1]
                for vn in value_numbers
            ]

            value = (instr['op'], *value_numbers)

            # if this instruction is itself a copy, then its value should just be that of what it's copying
            if instr['op'] == 'id':
                vn = value_numbers[0]
                value = value_table[vn][0]
            
            # commutativity - canonicalize for commutative operations
            if instr['op'] in ('add', 'mul', 'eq', 'and', 'or'):
                value_numbers.sort()
                value = (instr['op'], *value_numbers)

            # commutativity - canonicalize for symmetric comparison instructions
            if instr['op'] == 'gt':
                # a > b is equivalent to b < a
                value = ('lt', value[2], value[1])
            
            if instr['op'] == 'ge':
                # a >= b is equivalent to b <= a
                value = ('le', value[2], value[1])

            # constant fold for comparisons
            if instr['op'] in ('eq', 'le', 'ge') and value[1] == value[2]:
                value = ('bconst', True)

            if instr['op'] in ('lt', 'gt') and value[1] == value[2]:
                value = ('bconst', False)
        
        # helpers for constant folding
        def check_wrap(x):
            if -(1 << 64) <= x < 1 << 64:
                return x
            return (x % (1 << 64)) - 1 << 63
        def check_div(a, b):
            if b == 0:
                raise ArithmeticError
            return a // b
        def value_is_constant(value_table, value_number):
            return value_table[value_number][0][0] in ('iconst', 'bconst')
        def constant_value(value_table, value_number):
            return value_table[value_number][0][1]
        FOLDABLE_OPS = {
            'add': lambda a, b: check_wrap(a + b),
            'sub': lambda a, b: check_wrap(a - b),
            'mul': lambda a, b: check_wrap(a * b),
            'div': lambda a, b: check_div(a, b),
            'eq': lambda a, b: a == b,
            'lt': lambda a, b: a < b,
            'gt': lambda a, b: a > b,
            'le': lambda a, b: a <= b,
            'ge': lambda a, b: a >= b,
            'not': lambda x: not x,
            'and': lambda a, b: a and b,
            'or': lambda a, b: a or b
        }
        
        # perform constant folding
        if value[0] in FOLDABLE_OPS:
            arg_value_numbers = value[1:]
            op = FOLDABLE_OPS[value[0]]
            if all([value_is_constant(value_table, vn) for vn in arg_value_numbers]):
                argument_values = [constant_value(value_table, vn) for vn in arg_value_numbers]
                folded = op(*argument_values)
                vtype = 'bconst' if isinstance(folded, bool) else 'iconst'
                value = (vtype, folded)
        
        value_is_true = lambda vn: value_is_constant(value_table, vn) and constant_value(value_table, vn)
        value_is_false = lambda vn: value_is_constant(value_table, vn) and (not constant_value(value_table, vn))
        
        if value[0] == 'or':
            arg_value_numbers = value[1:]
            if any([value_is_true(vn) for vn in arg_value_numbers]):
                value = ('bconst', True)
        
        if value[0] == 'and':
            if any([value_is_false(vn) for vn in arg_value_numbers]):
                value = ('bconst', False)
        
        if value in value_map:
            # it is already in the table, so we can just replace it with a copy ('id')
            value_number = value_map[value]
            canonical_variable = value_table[value_number][1]

            dest = instr['dest']
            instr.clear()
            instr['op'] = 'id'
            instr['args'] = [canonical_variable]
            instr['dest'] = dest

            # constprop - if the value is actually a constant, then replace with const op
            value = value_table[value_number][0]
            if value[0] in ('bconst', 'iconst'):
                instr.clear()
                instr['op'] = 'const'
                instr['value'] = value[1]
                instr['type'] = 'bool' if isinstance(value[1], bool) else 'int'
                instr['dest'] = dest

            # update var2val with a new mapping to the existing value number
            var2val[dest] = value_number

        else:
            # it is not in the table, so it represents a value we've never seen yet in
            # this basic block
            value_number = len(value_table)

            # rematerialize the instruction based on the value
            if value[0] in ('bconst', 'iconst'):
                # rematerialize the full constant instruction
                # (this accomodates constprop, since value might not match op after doing folding)
                dest = instr['dest']
                instr.clear()
                instr['op'] = 'const'
                instr['value'] = value[1]
                instr['type'] = 'bool' if isinstance(value[1], bool) else 'int'
                instr['dest'] = dest
            else:
                # need to rewrite arguments
                new_args = []
                for arg in instr['args']:
                    arg_value_number = var2val[arg]
                    canonical_variable = value_table[arg_value_number][1]
                    new_args.append(canonical_variable)
                instr['args'] = new_args

            

            # add new value to value_map and value_table
            value_map[value] = value_number
            value_table.append((value, instr['dest']))

            # update var2val with a new mapping to the new value number
            var2val[instr['dest']] = value_number
    
    # we need to "repair" after renaming, since later basic blocks don't know that we've renamed stuff
    def repair_block(block, var_name_counts):
        for (var, count) in var_name_counts.items():
            if count > 1:
                copy = {
                    'op': 'id',
                    'args': [f'{var}__{count}'],
                    'dest': var,
                }
                block.append(copy)
    
    if 'op' in block[-1] and block[-1]['op'] in ('jmp', 'br', 'ret'):
        terminator = block.pop()
        repair_block(block, var_name_counts)
        block.append(terminator)
    else:
        repair_block(block, var_name_counts)

    return block


def lvn_pass(bril, do_dce):
    # perform local value numbering on each function, then run DCE pass from before
    for function in bril['functions']:
        new_instrs = []
        for block in form_blocks(function['instrs']):
            new_block = lvn(block)
            new_instrs.extend(new_block)
        
        function['instrs'] = new_instrs
    
    if do_dce:
        bril = dce(bril)
    
    return bril

def main():
    do_dce = not ('--no-dce' in sys.argv)


    out = lvn_pass(json.load(sys.stdin), do_dce)
    json.dump(out, sys.stdout)

if __name__ == '__main__':
    main()