import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from worksheet_question_types import ALL_TYPES, recommend_question_set, render_recommendation_for_prompt, list_by_category

print("Total types:", len(ALL_TYPES))
print(f"  vocab: {len(list_by_category('vocab'))}")
print(f"  sentence: {len(list_by_category('sentence'))}")
print(f"  reading: {len(list_by_category('reading'))}")
print()
for lvl in ["Smart", "1", "3", "5"]:
    print(f"=== Level {lvl} ===")
    for t in recommend_question_set(lvl):
        print(f"  [{t.category:8}] {'*' * t.stars:5} {t.en_instr[:60]}")
    print()
print("--- example prompt block for L5 ---")
print(render_recommendation_for_prompt("5"))
