import re
import html
from typing import List, Dict, Optional, Tuple

def parse_test_input(text: str) -> Tuple[List[Dict], List[str]]:
    """
    Parses the text input for tests.
    Format:
    1. Question text
    a. Option 1
    b. Option 2 (x)
    ...
    
    Returns:
        tuple: (list of parsed questions, list of errors)
    """
    lines = text.strip().split('\n')
    questions = []
    errors = []
    
    current_question = None
    current_options = []
    correct_index = -1
    
    # Regex for question start: "1. ", "2. ", etc.
    question_pattern = re.compile(r'^\d+\.\s+(.*)')
    # Regex for option start: "a. ", "b. ", "а. ", "б. " etc. (supports cyrillic)
    option_pattern = re.compile(r'^[a-zа-яєіїґ]\.\s+(.*)', re.IGNORECASE)
    # Regex for correct mark: (x), (х) - latin/cyrillic, case insensitive
    correct_mark_pattern = re.compile(r'\s*\([xхХ]\)\s*$')

    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        q_match = question_pattern.match(line)
        o_match = option_pattern.match(line)
        
        if q_match:
            # Save previous question if exists
            if current_question:
                if correct_index == -1:
                    errors.append(f"Питання '{current_question}' не має правильної відповіді.")
                elif len(current_options) < 2:
                    errors.append(f"Питання '{current_question}' має менше 2 варіантів.")
                else:
                    questions.append({
                        "question": current_question,
                        "options": current_options,
                        "correct_index": correct_index
                    })
            
            # Start new question
            current_question = q_match.group(1).strip()
            current_options = []
            correct_index = -1
            
        elif o_match:
            if current_question is None:
                errors.append(f"Знайдено варіант відповіді без питання: '{line}'")
                continue
                
            option_text = o_match.group(1).strip()
            is_correct = False
            
            # Check for (x) mark
            mark_match = correct_mark_pattern.search(option_text)
            if mark_match:
                is_correct = True
                # Remove the mark from text
                option_text = correct_mark_pattern.sub('', option_text).strip()
            
            current_options.append(option_text)
            if is_correct:
                if correct_index != -1:
                    errors.append(f"Питання '{current_question}' має більше однієї правильної відповіді.")
                correct_index = len(current_options) - 1
        else:
            # Continuation of previous line? Or junk? 
            # For simplicity, if we are inside a question or option, append to it.
            if current_options:
                current_options[-1] += " " + line
            elif current_question:
                current_question += " " + line
            else:
                # Ignore or treat as junk
                pass

    # Save last question
    if current_question:
        if correct_index == -1:
            errors.append(f"Питання '{current_question}' не має правильної відповіді.")
        elif len(current_options) < 2:
            errors.append(f"Питання '{current_question}' має менше 2 варіантів.")
        else:
            questions.append({
                "question": current_question,
                "options": current_options,
                "correct_index": correct_index
            })
            
    return questions, errors

def format_test_display(questions: List[Dict]) -> str:
    """Formats the parsed test back to string for display."""
    output = []
    for i, q in enumerate(questions, 1):
        q_text = html.escape(q['question'])
        output.append(f"<b>{i}. {q_text}</b>")
        for j, opt in enumerate(q['options']):
            opt_text = html.escape(opt)
            marker = " ✅" if j == q['correct_index'] else ""
            # Convert index to letter (0->a, 1->b)
            letter = chr(ord('a') + j)
            # Make correct answer bold
            if j == q['correct_index']:
                output.append(f"{letter}. <b>{opt_text}</b>{marker}")
            else:
                output.append(f"{letter}. {opt_text}")
        output.append("")
    return "\n".join(output)
