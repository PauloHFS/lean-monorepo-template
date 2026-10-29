import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { allowedFields, can, canClass, evaluateCond } from '../src/lib/permissions/engine'
import type { PolicyOut } from '../src/lib/permissions/types'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const fixturePath = path.resolve(__dirname, '../../api/tests/data/permissions_conformance.json')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf-8'))

test('Permissions Conformance: todas as condicoes ABAC produzem resultado identico ao Python', () => {
  for (const testCase of fixture.condition_cases) {
    if (testCase.expected === 'missing') {
      expect(() => {
        evaluateCond(testCase.cond, testCase.ctx)
      }).toThrow(/Missing attribute/)
    } else {
      const result = evaluateCond(testCase.cond, testCase.ctx)
      expect(result).toBe(testCase.expected)
    }
  }
})

test('Permissions Conformance: todas as acoes e recursos batem 100% com o backend', () => {
  for (const c of fixture.cases) {
    const policy = fixture.policies[c.actor] as PolicyOut
    const resultCan = can(policy, c.action, c.resource, c.entity)
    expect(resultCan).toBe(c.can)

    const resultCanClass = canClass(policy, c.action, c.resource)
    expect(resultCanClass).toBe(c.can_class)

    const fields = allowedFields(policy, c.action, c.resource, c.entity)
    const fieldsArray = fields === null ? null : Array.from(fields).sort()
    expect(fieldsArray).toEqual(c.fields)
  }
})
