"""Run from the target checkout: PYTHONPATH=backend/src python audit.py ARCHIVE OUTPUT_JSON."""
from collections import Counter
import json
from pathlib import Path
import re
import sys
import zipfile

from mail_search.application.spelling import correct_query

archive, output = sys.argv[1:]
tokens = Counter()
with zipfile.ZipFile(archive) as source:
    for line in source.open("documents.jsonl"):
        document = json.loads(line)["doc"]
        tokens.update(re.findall(r"(?<![\w/-])[а-яё]{4,28}(?![\w/-])", document))
changed = {}
for word, count in tokens.most_common(2500):
    corrected, _ = correct_query(word, preserve_forms=True)
    if corrected != word:
        changed[word] = {"occurrences":count, "corrected":corrected}
controls = [w for w in ("шаровый", "подкатного", "поворотник", "холдере",
                        "муниц.фонда", "соор.20", "6 наим. (комплект)", "кислородн. датчика")]
data = {
    "types":len(tokens), "scanned":min(2500,len(tokens)), "changed_single_tokens":changed,
    "control_phrases":{w:correct_query(w,preserve_forms=True)[0] for w in controls},
}
Path(output).write_text(json.dumps(data, ensure_ascii=False,indent=2)+"\n")
print(json.dumps(data["control_phrases"],ensure_ascii=False))
