"""Dataflow analysis (live variables)"""

import json
import sys

from assignments.form_blocks import form_blocks
from assignments.cfg import edges, block_map, add_terminators
from collections import deque

def live_variables_block(block_out, block_instrs):
    live_vars = set(block_out)
    for instr in reversed(block_instrs):
        # handle def (kill)
        if 'dest' in instr:
            if instr['dest'] in live_vars:
                live_vars.remove(instr['dest'])

        # handle uses
        for arg in instr.get('args', []):
            live_vars.add(arg)
    
    return live_vars

def live_variables_fn(cfg):
    blocks, preds, succs = cfg
    block_ins = {block_name: set() for block_name in blocks.keys()}
    block_outs = {block_name: set() for block_name in blocks.keys()}

    # initialize the worklist - all basic blocks with no successors
    # (i.e. basic blocks that return, either explicitly or implicitly)
    worklist = deque()
    worklist_s = set()

    for block_name, block_succs in succs.items():
        if not block_succs:
            worklist.append(block_name)
            worklist_s.add(block_name)

    while worklist:
        block_name = worklist.popleft()
        worklist_s.remove(block_name)

        block_succs = succs[block_name]
        if block_succs:
            # merge `block_in` of successors
            block_out = set()
            for block_succ in block_succs:
                block_out.update(block_ins[block_succ])

            block_outs[block_name] = block_out
        else:
            # no successors; should be initialized before algorithm begins
            block_out = block_outs[block_name]
        
        # apply transfer function
        block_instrs = blocks[block_name]
        block_in = live_variables_block(block_out, block_instrs)

        # add predecessors to worklist, if changed
        old_block_in = block_ins[block_name]
        block_ins[block_name] = block_in
        if block_in != old_block_in:
            block_preds = preds[block_name]
            for pred in block_preds:
                # if it's already on the worklist, don't put it in again
                if pred not in worklist_s:
                    worklist.append(pred)
                    worklist_s.add(pred)

    return block_ins, block_outs

def live_variables(bril):
    out = {}
    for function in bril['functions']:
        blocks = form_blocks(function['instrs'])
        blocks = block_map(blocks)
        add_terminators(blocks)
        cfg = (blocks, *edges(blocks))
        out[function['name']] = live_variables_fn(cfg)
    return out

def display(live_vars):
    for fn, fn_live_vars in live_vars.items():
        print(f'@{fn}')
        block_ins, block_outs = fn_live_vars
        block_names = block_ins.keys()
        for block_name in block_names:
            print(f'  {block_name}:')
            print(f'    live variables at end: {block_outs[block_name]}')
            print(f'    live variables at beginning: {block_ins[block_name]}')

# i don't have testing here, but i think that a good way to test this could be using interpreter
# at beginning / end of each basic block, use the live variable information and just straight up
# delete all the values which aren't live. if they actually aren't live, then this shouldn't
# cause issues! similarly, deleting any of the values which are claimed to be live by this analysis
# should break the program

def main():
    live_vars = live_variables(json.load(sys.stdin))
    display(live_vars)

if __name__ == '__main__':
    main()