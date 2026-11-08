"""Run from WorkflowKit root; pass one or more Python executable paths."""
import subprocess,sys
for executable in sys.argv[1:] or [sys.executable]:
    subprocess.run([executable,'-X','utf8','-B','-m','unittest','discover','-s','test/release',
                    '-p','syntax_context_test.py','-k','SyntaxEngineTests','-v'],check=True)
