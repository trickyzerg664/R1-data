import copy
from .errors import QuestionError
from .rules import PROMPT, parse, check_answer


def fresh(question):
    return dict(**question, status='in_progress', attempt=1, turn=0, phase='teacher',
                messages=[{'role': 'user', 'content': PROMPT.format(question=question['question'])}],
                turns=[], queries=[], history=[])


def process(question, store, teacher, retriever, cfg):
    task = store.get(question['id']) or fresh(question)
    if task['status'] in ('accepted', 'rejected'): return
    store.save(task)
    while task['status'] == 'in_progress':
        try:
            if task['phase'] == 'teacher':
                if task['turn'] >= cfg['max_turns']: raise QuestionError('max_turns')
                retriever.healthy()

                def commit(response, request, call_id):
                    task['turns'].append({'request': copy.deepcopy(request), 'response': response,
                                          'call_id': call_id, 'observation': None})
                    task['phase'] = 'parse'
                    store.finish_call(call_id, 'succeeded', {'response': response, 'request': request}, task)

                teacher.complete(task, commit)
            if task['phase'] == 'parse':
                try: text = task['turns'][-1]['response']['choices'][0]['message']['content']
                except (KeyError, IndexError, TypeError): raise QuestionError('invalid_output')
                action, value = parse(text)
                task['messages'].append({'role': 'assistant', 'content': text})
                task['turns'][-1]['action'] = action
                task['turns'][-1]['value'] = value
                task['turn'] += 1
                if action == 'search':
                    canonical = ' '.join(value.lower().split())
                    if canonical in task['queries']: raise QuestionError('repeated_search')
                    task['queries'].append(canonical)
                    task['phase'] = 'retrieve'
                else:
                    if len(task['queries']) < cfg['min_searches']: raise QuestionError('insufficient_searches')
                    if not check_answer(value, question['golden_answers']): raise QuestionError('wrong_answer')
                    task['final_answer'] = value
                    task['status'] = 'accepted'
                    task['phase'] = 'done'
                store.save(task)
            if task['phase'] == 'retrieve':
                query = task['turns'][-1]['value']
                docs = retriever.search(query)
                task['turns'][-1]['observation'] = docs
                rendered = '\n'.join(f"Doc {i+1}: {d['document']['contents']}" for i, d in enumerate(docs))
                task['messages'].append({'role': 'user', 'content': '<information>' + rendered + '</information>'})
                task['phase'] = 'teacher'
                store.retrieval(task)
        except QuestionError as exc:
            kind = str(exc)
            store.error(kind)
            task['history'].append(dict(attempt=task['attempt'], reason=kind, turns=task['turns'], messages=task['messages']))
            if task['attempt'] >= cfg['max_attempts']:
                task['status'], task['phase'], task['failure_reason'] = 'rejected', 'done', kind
            else:
                nxt = fresh(question)
                nxt['attempt'], nxt['history'] = task['attempt'] + 1, task['history']
                task = nxt
            store.save(task)
