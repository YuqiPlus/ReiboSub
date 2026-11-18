"""Narrow, independently approved rolling-caption tail coverage.

Never deletes text from an input. Only an already-empty translation for an
overlapping Korean grammatical tail may be omitted from a delivery COPY.
"""
import re


def covered_tails(rows,proposals,reviews):
    by_id={r['id']:r for r in rows};covered=[]
    def quotes_valid(evidence):
        return isinstance(evidence,list) and bool(evidence) and all(isinstance(e,dict)
            and type(e.get('id')) is int and e['id'] in by_id and isinstance(e.get('quote'),str)
            and e['quote'].strip() and e['quote'] in by_id[e['id']]['source'] for e in evidence)
    for position,row in enumerate(rows):
        key=str(row['id']);p=proposals.get(key,{});review=reviews.get(key,{})
        if row['zh'].strip() or p.get('action')!='keep' or p.get('replacement') is not None or review.get('verdict')!='approve':continue
        if not re.fullmatch(r'(?:니다|습니다)[.!?。！？…\s]*',row['source'].strip()):continue
        if not quotes_valid(p.get('evidence')) or not quotes_valid(review.get('evidence')):continue
        citations={e['id'] for e in p['evidence']}&{e['id'] for e in review['evidence']}
        if row['id'] not in citations:continue
        tail=row['source'].strip().rstrip('.!?。！？… \t\r\n')
        for parent in reversed(rows[max(0,position-2):position]):
            body=parent['source'].strip().rstrip('.!?。！？… \t\r\n')
            if parent['id'] not in citations or not parent['zh'].strip() or len(body)<=len(tail) or not body.endswith(tail):continue
            if not parent['start']<=row['start']<row['end']<=parent['end']:continue
            covered.append({'id':row['id'],'covered_by':parent['id'],'kind':'approved_overlapping_ending',
                'source':row['source'],'parent_source':parent['source'],'parent_translation':parent['zh'],
                'interval':[row['start'],row['end']],
                'reason_zh':'相邻完整原句及其译文已覆盖这个重叠词尾；提案与独立复核均批准保留空译文，仅交付副本移除空块。'})
            break
    return covered
