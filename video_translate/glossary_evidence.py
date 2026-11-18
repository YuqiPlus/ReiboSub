"""Deterministic glossary-to-subtitle evidence locations; no model requests."""
from collections import Counter
import math


def evidence_locations(cues, ids, source='', aliases=()):
    counts=Counter(c.index for c in cues)
    rows=sorted((c for c in cues if counts[c.index]==1 and type(c.index) is int
        and math.isfinite(c.start) and math.isfinite(c.end) and 0<=c.start<c.end and c.text.strip()),
        key=lambda c:(c.start,c.end,c.index))
    known={c.index for c in rows}
    wanted=list(dict.fromkeys(i for i in ids if type(i) is int))
    missing=[i for i in wanted if i not in known]
    selected=[c for c in rows if c.index in wanted]
    method='evidence_id'
    keys=[v.strip().casefold() for v in [source,*aliases] if isinstance(v,str) and v.strip()]
    if not selected:
        # Exact literal occurrences are useful for old glossary drafts with no
        # evidence IDs. Do not invent approximate/fuzzy time locations.
        selected=[c for c in rows if any(key in c.text.casefold() for key in keys)]
        method='literal_match'
    positions={c.index:i for i,c in enumerate(rows)}
    evidence=[]
    for cue in selected[:12]:
        i=positions[cue.index]
        evidence.append({'cue_id':cue.index,'start':cue.start,'end':cue.end,'text':cue.text,
            'match_method':method,'literal_match':any(key in cue.text.casefold() for key in keys),
            'context':[{'cue_id':c.index,'start':c.start,'end':c.end,'text':c.text,'is_evidence':c.index==cue.index}
                       for c in rows[max(0,i-2):i+3]]})
    return {'evidence':evidence,'total_occurrences':len(selected),'truncated':len(selected)>12,'missing_ids':missing}
