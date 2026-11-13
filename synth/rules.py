import re
import string
from .errors import QuestionError

PROMPT = '''Answer the given question. Conduct reasoning inside <think> and </think>.
Each response must contain exactly one action: <search>query</search> OR <answer>short answer</answer>.
Search results will be supplied by the system inside <information> and </information>.
Never invent search results. Search at least once before giving the final answer.
Question: {question}'''


def normalize(text):
    text = text.lower().translate(str.maketrans('', '', string.punctuation))
    return ' '.join(re.sub(r'\b(a|an|the)\b', ' ', text).split())


def parse(text):
    if not isinstance(text, str): raise QuestionError('invalid_output')
    match = re.fullmatch(r'\s*<think>.+?</think>\s*<(search|answer)>([^<>]+)</\1>\s*', text, re.S)
    if not match or any(text.count(tag) != 1 for tag in ('<think>', '</think>')):
        raise QuestionError('invalid_format')
    if sum(text.count(tag) for tag in ('<search>', '<answer>')) != 1 or re.search(r'<think>\s*</think>',text):
        raise QuestionError('invalid_format')
    if '<information>' in text: raise QuestionError('fabricated_observation')
    action, value = match.group(1), match.group(2).strip()
    if not value: raise QuestionError('empty_action')
    return action, value


def check_answer(answer, aliases):
    value = normalize(answer)
    return bool(value) and any(value == normalize(a) for a in aliases)
