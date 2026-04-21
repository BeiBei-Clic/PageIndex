src = main

pdf: clean cover.pdf main.tex body.tex
	latexmk $(src) -xelatex

show:
	xdg-open $(src).pdf

clean:
	-@rm -rf \
		*~ \
		*.aux \
		*.bbl \
		*.blg \
		*.bcf \
		*.dvi \
		*.ent \
		*.fdb_latexmk \
		*.fls \
		*.hd \
		*.loa \
		*.lof \
		*.lot \
		*.toc \
		*.log \
		*.out \
		.fuse* \
		*.run.xml \
		*.xdv \
		*.synctex.gz
	-@find . -name '*.aux' -exec rm {} \;
