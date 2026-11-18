"""Continue a saved Agent review, limited to explicitly selected issue IDs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from video_translate.agent.translation_review import review_translation_cues


def main():
    parser=argparse.ArgumentParser(description='复核已生成译文的指定疑点，另存局部修订版，不重翻整片')
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--cue-ids',type=int,nargs='+',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    state=json.loads(args.state.read_text(encoding='utf-8'))
    issues=state.get('verification',{}).get('issues',[])
    known={row.get('id') for row in issues if row.get('kind') in {'translation_error','semantic_uncertain'}}
    if set(args.cue_ids)-known:raise ValueError('只能处理这个已存档任务中明确列出的译文疑点')
    source=state['sources'][state['selected']]['path']
    result=review_translation_cues(source,state['translated'],issues,args.cue_ids,args.output_dir)
    print(json.dumps({k:result[k] for k in ('translated_srt','audit','changed_ids','unresolved_ids','all_timing_unchanged','all_other_text_unchanged')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
