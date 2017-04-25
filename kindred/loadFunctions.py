import codecs
import os
import json
from pprint import pprint
import sys
import re
from collections import OrderedDict

from xml.dom import minidom

import kindred
import kindred.bioc

def loadEntity(line,text):
	assert line[0] == 'T', "Entity input should start with a T"
	split = line.strip().split('\t')
	assert len(split) == 3
	entityID = split[0]
	typeInfo = split[1]
	tokens = split[2]
		
	textChunks = []
	typeSpacePos = typeInfo.index(' ')
	typeName = typeInfo[:typeSpacePos]
	positionText = typeInfo[typeSpacePos:]
	positions = []
	for coordinates in positionText.strip().split(';'):
		a,b = coordinates.strip().split(' ')
		a,b = int(a.strip()),int(b.strip())
		textChunk = text[a:b].replace('\n',' ').strip()
		textChunks.append(textChunk)
		positions.append((a,b))
		
	# Check that the tokens match up to the text
	chunkTest = " ".join(textChunks)
	tokensTest = tokens
	chunkTest = re.sub(r'\s\s+', ' ', chunkTest)
	tokensTest = re.sub(r'\s\s+', ' ', tokensTest)
	chunkTest = chunkTest.strip()
	tokensTest = tokensTest.strip()

	#print chunkTest, '|', tokensTest
	assert chunkTest == tokensTest , u"For id=" + entityID + ", tokens '" + tokens.encode('ascii', 'ignore') + "' don't match up with positions: " + str(positions)
	
	entity = kindred.Entity(typeName, tokensTest, positions, entityID)

	return entity
	
def loadRelation(line,ignoreComplexRelations=False):
	assert line[0] == 'E' or line[0] == 'R', "Relation input should start with a E or R"
	split = line.strip().split('\t')
	relationID = split[0]
	eventInfo = split[1]
	typeSpacePos = eventInfo.index(' ')
	

	eventNameSplit = eventInfo[:typeSpacePos].split(':')
	assert len(eventNameSplit) == 1, "Cannot load trigger events"
	relationType = eventNameSplit[0]
		
	isComplexRelation = False
	argumentText = eventInfo[typeSpacePos:]
	arguments = []
	for argument in argumentText.strip().split(' '):
		split2 = argument.strip().split(':')
		assert len(split2) == 2
		argName = split2[0]
		entityID = split2[1]

		isComplexRelation = (entityID[0] == 'R' or entityID[0] == 'E')

		# We'll skip this relation as
		if ignoreComplexRelations and isComplexRelation:
			break

		assert not isComplexRelation, "kindred does not support complex relations (where one relation has another relation as an argument), use ignoreComplexRelations=True to ignore these"

		assert not argName in arguments
		arguments.append((argName,entityID))

	if ignoreComplexRelations and isComplexRelation:
		return None

	arguments = sorted(arguments)
	entityIDs = [ entityID for argName,entityID in arguments ]
	argNames = [ argName for argName,entityID in arguments ]

	relation = kindred.Relation(relationType, entityIDs, argNames)
	return relation
	
# TODO: Deal with complex relations more clearly
def loadDataFromSTFormat(txtFile,a1File,a2File,verbose=False,ignoreEntities=[],ignoreComplexRelations=True):
	with codecs.open(txtFile, "r", "utf-8") as f:
		text = f.read()
			
	entities = []
	with codecs.open(a1File, "r", "utf-8") as f:
		for line in f:
			if line.strip() == '':
				continue
				
			assert line[0] == 'T', "Only triggers are expected in a1 file: " + a1File
			entity = loadEntity(line.strip(), text)
			if (not entity is None) and (not entity.entityType in ignoreEntities):
				entities.append(entity)
			
	relations = []
	if os.path.exists(a2File):
		with codecs.open(a2File, "r", "utf-8") as f:
			for line in f:
				if line.strip() == '':
					continue
					
				if line[0] == 'E' or line[0] == 'R':
					relation = loadRelation(line.strip(),ignoreComplexRelations)
					if not relation is None:
						relations.append(relation)
				elif verbose:
					print("Unable to process line: %s" % line.strip())
	elif verbose:
		print("Note: No A2 file found. ", a2File)

	baseTxtFile = os.path.basename(txtFile)
	combinedData = kindred.RelationData(text,relations,entities=entities,sourceFilename=baseTxtFile)
			
	return combinedData

def parseJSON(data,ignoreEntities=[]):
	entities = []
	relations = []
	
	text = data['text']
	if 'denotations' in data:
		for d in data['denotations']:
			sourceEntityID = None
			if 'id' in d:
				sourceEntityID = d['id']
			
			entityType = d['obj']
			span = d['span']
			startPos,endPos = span['begin'],span['end']
			position = [(startPos,endPos)]
			entityText = text[startPos:endPos]
			
			if not entityType in ignoreEntities:
				entity = kindred.Entity(entityType,entityText,position,sourceEntityID=sourceEntityID)
				entities.append(entity)
	if 'relations' in data:
		for r in data['relations']:
			relationID = r['id']
			obj = r['obj']
			relationType = r['pred']
			subj = r['subj']
			
			entityIDs = [obj,subj]
			argNames = ['obj','subj']
			
			relation = kindred.Relation(relationType=relationType,entityIDs=entityIDs,argNames=argNames)
			relations.append(relation)
	#if 'modifications' in data:
	#	for m in data['modifications']:
	#		id = m['id']
	#		obj = m['obj']
	#		pred = m['pred']
	#		modification = (pred,obj)
	#		modifications[id] = modification

	#print "keys:", list(data.keys())
	expected = ['denotations','divid','modifications','namespaces','project','relations','sourcedb','sourceid','target','text','tracks']
	extraFields = [ k for k in data.keys() if not k in expected]
	assert len(extraFields) == 0, "Found additional unexpected fields (%s) in JSON" % (",".join(extraFields))
		
	combinedData = kindred.RelationData(text,relations,entities=entities)

	return combinedData

def loadDataFromJSON(filename,ignoreEntities=[]):
	with open(filename) as f:
		data = json.load(f)
	parsed = parseJSON(data,ignoreEntities)
	
	baseTxtFile = os.path.basename(filename)
	parsed.sourceFilename = baseTxtFile
	
	return parsed
	
def parseSimpleTag_helper(node,currentPosition=0,ignoreEntities=[]):
	text,entities,relations = '',[],[]
	for s in node.childNodes:
		if s.nodeType == s.ELEMENT_NODE:
			insideText,insideEntities,insideRelations = parseSimpleTag_helper(s,currentPosition+len(text))

			if s.tagName == 'relation':
				relationType = s.getAttribute('type')
				arguments = [ (argName,entityID) for argName,entityID in s.attributes.items() if argName != 'type' ]
				arguments = sorted(arguments)
				
				entityIDs = [ entityID for argName,entityID in arguments]
				argNames = [ argName for argName,entityID in arguments]
				
				r = kindred.Relation(relationType=relationType,entityIDs=entityIDs,argNames=argNames)
				relations.append(r)
			else: # Entity
				entityType = s.tagName
				sourceEntityID = s.getAttribute('id')
				position = [(currentPosition+len(text),currentPosition+len(text)+len(insideText))]
				if not entityType in ignoreEntities:
					e = kindred.Entity(entityType,insideText,position,sourceEntityID=sourceEntityID)
					entities.append(e)
				
			text += insideText
			entities += insideEntities
			relations += insideRelations
		elif s.nodeType == s.TEXT_NODE:
			text += s.nodeValue
			
	return text,entities,relations
	
def mergeEntitiesWithMatchingIDs(unmergedEntities):
	assert isinstance(unmergedEntities,list)

	entityDict = OrderedDict()
	for e in unmergedEntities:
		assert isinstance(e, kindred.Entity)
		if e.sourceEntityID in entityDict:
			position = e.position
			entityDict[e.sourceEntityID].text += " " + e.text
			entityDict[e.sourceEntityID].position += e.position
		else:
			entityDict[e.sourceEntityID] = e
			
	return list(entityDict.values())
	
def parseSimpleTag(text,ignoreEntities=[]):
	xmldoc = minidom.parseString("<doc>%s</doc>" % text)
	docNode = xmldoc.childNodes[0]
	text,unmergedEntities,relations = parseSimpleTag_helper(docNode,ignoreEntities=ignoreEntities)
	
	missingSourceEntityID = [ e.sourceEntityID == '' for e in unmergedEntities ]
	assert all(missingSourceEntityID) or (not any(missingSourceEntityID)), 'All entities or none (not some) should be given IDs'
	assert (not any(missingSourceEntityID)) or len(relations) == 0, "Cannot include relations with no-ID entities"
	
	if all(missingSourceEntityID):
		for i,e in enumerate(unmergedEntities):
			e.sourceEntityID = i+1
					
	entities = mergeEntitiesWithMatchingIDs(unmergedEntities)
			
	combinedData = kindred.RelationData(text,relations,entities=entities)
	return combinedData

def loadDataFromBioC(filename,ignoreEntities=[]):
	reader = kindred.bioc.BioCReader(filename)
	reader.read()
	
	parsed = []
	
	assert isinstance(reader.collection,kindred.bioc.BioCCollection)
	
	for document in reader.collection:
		assert isinstance(document,kindred.bioc.BioCDocument)
		for passage in document.passages:
			assert isinstance(passage,kindred.bioc.BioCPassage)
			
			text = passage.text
			entities = []
			relations = []
			
			for a in passage.annotations:
				assert isinstance(a,kindred.bioc.BioCAnnotation)
				
				entityType = a.infons['type']
				sourceEntityID = a.id
				
				position = []
				segments = []
				
				for l in a.locations:
					assert isinstance(l,kindred.bioc.BioCLocation)
					startPos = int(l.offset)
					endPos = startPos + int(l.length)
					position.append((startPos,endPos))
					segments.append(text[startPos:endPos])
				
				entityText = " ".join(segments)
				
				e = kindred.Entity(entityType,entityText,position,sourceEntityID)
				entities.append(e)
				
			for r in passage.relations:
				assert isinstance(r,kindred.bioc.BioCRelation)
				relationID = r.id
				relationType = r.infons['type']
				
				arguments = []
				for n in r.nodes:
					assert isinstance(n,kindred.bioc.BioCNode)
					arguments.append((n.role,n.refid))
				arguments = sorted(arguments)
					
				entityIDs = [ entityID for argName,entityID in arguments]
				argNames = [ argName for argName,entityID in arguments]
				
				r = kindred.Relation(relationType=relationType,entityIDs=entityIDs,argNames=argNames)
				relations.append(r)
				
			relData = kindred.RelationData(text,relations,entities=entities)
			parsed.append(relData)
			
	return parsed
	
	
def load(dataFormat,path=None,txtPath=None,a1Path=None,a2Path=None,verbose=False,ignoreEntities=[],ignoreComplexRelations=False):
	assert dataFormat == 'standoff' or dataFormat == 'simpletag' or dataFormat == 'json' or dataFormat == 'bioc'
	
	if dataFormat == 'standoff':
		assert not txtPath is None
		assert not a1Path is None
		#assert not a2Path is None

		relationData = loadDataFromSTFormat(txtPath,a1Path,a2Path,verbose=verbose,ignoreEntities=ignoreEntities)
		relationData = [relationData]
	elif dataFormat == 'simpletag':
		assert not path is None

		with open(path,'r') as f:
			filecontents = f.read().strip()
		relationData = parseSimpleTag(filecontents,ignoreEntities=ignoreEntities)
		relationData.sourceFilename = os.path.basename(path)
		relationData = [relationData]
	elif dataFormat == 'json':
		assert not path is None
		relationData = loadDataFromJSON(path,ignoreEntities=ignoreEntities)
		relationData = [relationData]
	elif dataFormat == 'bioc':
		assert not path is None
		relationData = loadDataFromBioC(path,ignoreEntities=ignoreEntities)
		
	assert isinstance(relationData,list)
	for r in relationData:
		assert isinstance(r,kindred.RelationData)
		
	return relationData
	
def loadDir(dataFormat,directory,verbose=False,ignoreEntities=[],ignoreComplexRelations=False):
	assert dataFormat == 'standoff' or dataFormat == 'simpletag' or dataFormat == 'json' or dataFormat == 'bioc'
	assert os.path.isdir(directory), "%s must be a directory"
	
	if directory[-1] != '/':
		directory += '/'

	allData = []
	for filename in os.listdir(directory):
		if dataFormat == 'standoff' and filename.endswith('.txt'):
			base = filename[0:-4]
			txtPath = directory + base + '.txt'
			a1Path = directory + base + '.a1'
			a2Path = directory + base + '.a2'

			assert os.path.isfile(txtPath), "%s must exist" % txtPath
			assert os.path.isfile(a1Path), "%s must exist" % a1Path

			data = load(dataFormat,txtPath=txtPath,a1Path=a1Path,a2Path=a2Path,verbose=verbose,ignoreEntities=ignoreEntities,ignoreComplexRelations=ignoreComplexRelations)
			allData += data
		elif dataFormat == 'simpletag' and filename.endswith('.simple'):
			data = load(dataFormat,path=filename,verbose=verbose,ignoreEntities=ignoreEntities,ignoreComplexRelations=ignoreComplexRelations)
			allData += data
		elif dataFormat == 'json' and filename.endswith('.json'):
			data = load(dataFormat,path=filename,verbose=verbose,ignoreEntities=ignoreEntities,ignoreComplexRelations=ignoreComplexRelations)
			allData += data
		elif dataFormat == 'bioc' and filename.endswith('.bioc.xml'):
			data = load(dataFormat,path=filename,verbose=verbose,ignoreEntities=ignoreEntities,ignoreComplexRelations=ignoreComplexRelations)
			allData += data
			
	return allData
			
			