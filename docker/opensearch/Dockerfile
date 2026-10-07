FROM opensearchproject/opensearch:3.5.0
# ICU: Unicode tokenisation + Devanagari->Latin transliteration for Hinglish-friendly analysis.
RUN /usr/share/opensearch/bin/opensearch-plugin install --batch analysis-icu
