"""Dominance analysis"""

import json
import sys

from assignments.form_blocks import form_blocks
from assignments.cfg import edges, block_map, add_terminators, add_entry

def dominators(cfg):
    # produces sets of blocks that a block dominates
    blocks, preds, succs = cfg
    dom = {block_name: set(blocks.keys()) for block_name in blocks.keys()}
    entry = next(iter(blocks.keys()))

    dom[entry] = {entry}
    
    # post-order traversal onto a stack
    post_order_stack = []
    visited = set()
    def dfs(block):
        if block in visited:
            return
        
        visited.add(block)
        for succ in succs[block]:
            dfs(succ)
        
        post_order_stack.append(block)

    dfs(entry)

    changing = True
    while changing:
        changing = False

        for block in reversed(post_order_stack):
            if block == entry:
                continue

            block_preds = preds[block]
            old_dom = dom[block]
            new_dom = set.union({block}, set.intersection(*[dom[pred] for pred in block_preds]))
            
            if new_dom != old_dom:
                changing = True
                dom[block] = new_dom

    return dom

def dominance_tree(cfg, dom_sets):
    pass

def dominance_frontiers(cfg, dom_sets):
    pass


def dominance_analysis(bril):
    out = {}
    for function in bril['functions']:
        blocks = form_blocks(function['instrs'])
        blocks = block_map(blocks)
        add_entry(blocks)
        add_terminators(blocks)
        cfg = (blocks, *edges(blocks))

        dom_sets = dominators(cfg)
        dom_tree = dominance_tree(cfg, dom_sets)
        dom_frontiers = dominance_frontiers(cfg, dom_sets)

        out[function['name']] = {
            'sets': dom_sets,
            'tree': dom_tree,
            'frontier': dom_frontiers
        }

    return out

def main():
    out = dominance_analysis(json.load(sys.stdin))

if __name__ == '__main__':
    main()