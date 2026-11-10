# Build settings for the Green IT 2026 deliverables. You do not need to
# open this file, and you should not need to change it.
#
# Run `latexmk` from THIS directory. It builds every document in src/.

$pdf_mode      = 1;                     # pdfLaTeX; no XeLaTeX, no LuaLaTeX
$pdflatex      = 'pdflatex -interaction=nonstopmode -halt-on-error %O %S';

# The two short-paper files are the same paper for two kinds of object: a web
# page (-mics) and an HPC job (-hpc). You write ONE of them. glob() is what
# lets you delete the other: the build then simply has one less file to make.
@default_files = (glob('src/short-paper-*.tex'),
                  'src/peer-review-1.tex',
                  'src/peer-review-2.tex',
                  'src/response-to-reviewers.tex');

# pdf/ holds ONLY the finished PDFs. It is the folder you upload from,
# so nothing else is allowed to land in it. The .aux, .log and .bbl noise goes
# into .aux/, which is git-ignored and which `latexmk -c` empties.
$out_dir       = 'pdf';
$aux_dir       = '.aux';

# TeX resolves \bibliography and \includegraphics against the CURRENT
# DIRECTORY, not against the .tex file that asks for them. Since you run
# latexmk from here and the sources live in src/, these two lines are what
# let src/short-paper-mics.tex say \bibliography{refs} and find src/refs.bib.
# Put your figures in src/ too and \includegraphics{myfigure.png} works.
# The trailing colon means "then look in the usual places as well".
$ENV{TEXINPUTS} = 'src:' . ($ENV{TEXINPUTS} // '');
$ENV{BIBINPUTS} = 'src:' . ($ENV{BIBINPUTS} // '');

$clean_ext     = 'bbl run.xml synctex.gz';
