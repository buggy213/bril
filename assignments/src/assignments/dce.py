"""Perform basic dead code elimination on bril"""

import json
import sys
from assignments.form_blocks import form_blocks

# perform a trivial form of DCE that works on the whole function, where
# operations whose value is never used are simply removed. value generating
# operations in bril do not have side effects, so this kind of removal is safe

# returns: updated instrs, whether any instruction was removed
def global_dce(instrs):
    used = set()
    output = []
    modified = False

    for instr in instrs:
        for arg in instr.get('args', []):
            used.add(arg)
    
    for instr in instrs:
        if 'dest' not in instr or instr['dest'] in used:
            output.append(instr)
        else:
            modified = True
    
    return output, modified

    
# performs DCE within a single basic block that removes operations whose
# results are never used due to a later instruction that overrides it
def local_dce(instrs):
    output = []
    modified = False
    for block in form_blocks(instrs):
        # dictionary of values and associated removal candidate instructions
        # value name -> index of latest instruction writing to it
        not_yet_used = {}
        removed_indices = [] 
        for idx, instr in enumerate(block):
            # handle uses
            for arg in instr.get('args', []):
                # they might come from outside this basic block
                not_yet_used.pop(arg, None)
            
            # handle definitions
            if 'dest' in instr:
                dest = instr['dest']
                if dest in not_yet_used:
                    # previous instruction is dead
                    removed_indices.append(not_yet_used[dest])
                not_yet_used[dest] = idx
        
        # not efficient, but whatever
        for idx, instr in enumerate(block):
            if idx not in removed_indices:
                output.append(instr)

        if len(removed_indices) != 0:
            modified = True


    return output, modified

# fixed-point wrapper for `global_dce` and `local_dce`
def dce(bril):
    for function in bril['functions']:
        modified = True
        current_instrs = function['instrs']
        while modified:
            current_instrs, global_dce_modified = global_dce(current_instrs)
            current_instrs, local_dce_modified = local_dce(current_instrs)
            modified = global_dce_modified or local_dce_modified
        
        function['instrs'] = current_instrs
    
    return bril

def main():
    out = dce(json.load(sys.stdin))
    json.dump(out, sys.stdout)

if __name__ == '__main__':
    main()