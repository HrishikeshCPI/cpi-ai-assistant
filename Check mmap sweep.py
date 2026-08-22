import re
 
text = open("mmap_sweep.txt", encoding="utf-16").read()
 
functions = re.findall(r'"function":\s*(\S+)', text)
non_null = [f.rstrip(",") for f in functions if f.rstrip(",") != "null"]
 
warnings_blocks = re.findall(r'"parse_warnings":\s*\[([^\]]*)\]', text)
non_empty_warnings = [w.strip() for w in warnings_blocks if w.strip() != ""]
 
print("Total function fields found:", len(functions))
print("Non-null function values:", non_null)
print("Total parse_warnings arrays found:", len(warnings_blocks))
print("Non-empty warnings:", non_empty_warnings)
 