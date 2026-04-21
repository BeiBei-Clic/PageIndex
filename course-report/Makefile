src = main
cover = cover

pdf: clean cover.tex main.tex body.tex
	latexmk $(cover) -xelatex
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
		*.synctex.gz \
		cover.pdf
	-@find . -name '*.aux' -exec rm {} \;
