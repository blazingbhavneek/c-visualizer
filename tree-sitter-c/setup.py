from os import path
from platform import system
from sysconfig import get_config_var
from setuptools import Extension, find_packages, setup
from setuptools.command.build import build
from setuptools.command.egg_info import egg_info
try:
    from setuptools.command.bdist_wheel import bdist_wheel
except ImportError:
    from wheel.bdist_wheel import bdist_wheel

# 1. Define the base directory (where setup.py lives)
base_dir = path.dirname(__file__)

# 2. Paths must be relative to the PROJECT ROOT, 
# but we need to ensure they are found regardless of package_dir
sources = [
    "bindings/python/tree_sitter_custom/binding.c",
    "src/parser.c",
]
if path.exists("src/scanner.c"):
    sources.append("src/scanner.c")

if path.exists(path.join(base_dir, "src/scanner.c")):
    sources.append(path.join(base_dir, "src/scanner.c"))

macros = [
    ("PY_SSIZE_T_CLEAN", None),
    ("TREE_SITTER_HIDE_SYMBOLS", None),
]
if not get_config_var("Py_GIL_DISABLED"):
    macros.append(("Py_LIMITED_API", "0x030A0000"))

cflags = ["-std=c11", "-fvisibility=hidden"] if system() != "Windows" else ["/std:c11", "/utf-8"]

setup(
    # This tells setuptools where the Python code lives
    packages=find_packages("bindings/python"),
    package_dir={"": "bindings/python"},
    
    # This ensures the .pyi and other data files are found in the right spot
    package_data={
        "tree_sitter_custom": ["*.pyi", "py.typed"],
        "tree_sitter_custom.queries": ["*.scm"],
    },
    
    ext_modules=[
        Extension(
            name="tree_sitter_custom._binding", # Full dotted name is safer
            sources=sources,
            extra_compile_args=cflags,
            define_macros=macros,
            include_dirs=[path.join(base_dir, "src")], # Absolute path to src
            py_limited_api=True,
        )
    ],
    # ... rest of your custom classes (Build, BdistWheel, EggInfo) ...
    cmdclass={
        "build": build,
        "bdist_wheel": bdist_wheel,
        "egg_info": egg_info,
    },
    zip_safe=False,
)