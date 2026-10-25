"""Bounded deterministic arithmetic. No eval, imports or arbitrary function calls."""
import ast
import math
import operator
import re

OPS = {ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,
       ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow}

def safe_expression(expression):
    if len(expression) > 160:
        raise ValueError('Expression too long.')
    tree = ast.parse(expression, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 50:
        raise ValueError('Expression too complex.')
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):
            result = node.value
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
            result = (-1 if isinstance(node.op,ast.USub) else 1)*visit(node.operand)
        elif isinstance(node,ast.BinOp) and type(node.op) in OPS:
            a,b = visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Pow) and (abs(b)>12 or abs(a)>1e6):
                raise ValueError('Power exceeds the safe calculation limit.')
            result = OPS[type(node.op)](a,b)
        else:
            raise ValueError('Only numbers and arithmetic operators are supported.')
        if not isinstance(result,(int,float)) or not math.isfinite(result) or abs(result)>1e15:
            raise ValueError('Result exceeds the safe calculation limit.')
        return result
    return visit(tree.body)

def calculate(question):
    q = re.sub(r'^(?:calculate|compute|what is|what\'s)\s+', '', question.strip().lower()).rstrip(' ?')
    m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)', q)
    if m:
        q = f'({m[1]}/100)*{m[2]}'
    root = re.fullmatch(r'(?:the\s+)?square root of\s+(\d+(?:\.\d+)?)',q)
    factorial = re.fullmatch(r'(?:the\s+)?factorial of\s+(\d{1,3})',q)
    try:
        if root:
            value = math.sqrt(float(root[1]))
        elif factorial:
            n = int(factorial[1])
            if n > 100:
                return 'Factorials are limited to 100 in the local calculator.'
            return str(math.factorial(n))
        elif re.fullmatch(r'[\d\s.+*/%()^\-]+',q) and re.search(r'\d',q):
            value = safe_expression(q.replace('^','**'))
        else:
            return None
        return str(int(value)) if value == int(value) else format(value,'.12g')
    except (ValueError,SyntaxError,ZeroDivisionError,OverflowError,RecursionError) as e:
        return f'I could not calculate that safely: {e}'
