repo = localhost/test

build: software-push data-push
software-build:
	cd software ; docker build -t $(repo)/cplice-software:latest .

data-build:
	cd data ; docker build -t $(repo)/cplice-data:latest .

data-push: data-build
	docker push $(repo)/cplice-data:latest

software-push: software-build
	docker push $(repo)/cplice-software:latest

.PHONY: software-build data-build software-push data-push

cplice:
	python cplice.py -k localhost/test/cplice-software:latest localhost/test/cplice-data:latest localhost/test/cplice:latest
