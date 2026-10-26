import re
with open("re_audit.py") as f:
    content = f.read()
for num in range(1, 10):
    content = content.replace(f"adv_passed += 1", f"adv_passed += 1; print('ADV-0X passed')", 1).replace("0X", f"0{num}")
with open("re_audit_debug.py", "w") as f:
    f.write(content)
