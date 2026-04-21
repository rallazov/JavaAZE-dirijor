// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
// @vitest-environment node
//
// Unit tests for the pure HTTP-client module (Story 2.1 AC 8). Runs in
// Vitest's node env — `postRealmSpin` / `getRealmJob` only need a
// `global.fetch` stub, no DOM. Same scaffold as `dirijor-realtime.test.ts`.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_API_BASE,
  deleteRealmJob,
  getRealmJob,
  ImportDraftApiError,
  postMarketplaceImportDraft,
  postRealmSpin,
  resolveDirijorApiUrl,
  SpinApiError,
} from './dirijor-api';
import type { SpinJob, SpinResponse } from '@/types/spin';

const VALID_SPIN_RESPONSE: SpinResponse = {
  job_id: '5f1c0b2e-3d4a-4f5b-8c7d-9e0a1b2c3d4e',
  realm_id: 'realm-5f1c0b2e',
  phase: 'validating',
  adapter: 'local-noop',
  created_at: '2026-04-17T10:12:44.117Z',
  status_url: '/realms/5f1c0b2e-3d4a-4f5b-8c7d-9e0a1b2c3d4e',
  schema_version: 4,
};

const VALID_SPIN_JOB: SpinJob = {
  ...VALID_SPIN_RESPONSE,
  phase: 'ready',
  updated_at: '2026-04-17T10:12:44.627Z',
  realm_description: 'finance-swarm prod',
  agent_count: 3,
  outputs: {
    mesh_endpoint: 'noop://realm-5f1c0b2e',
    adapter: 'local-noop',
    agent_count: 3,
  },
  error: null,
};

function mockJsonResponse(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    async json() {
      return body;
    },
  } as unknown as Response;
}

function mockBadJsonResponse(status: number): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    async json() {
      throw new SyntaxError('unexpected token');
    },
  } as unknown as Response;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('resolveDirijorApiUrl', () => {
  it('returns DEFAULT_API_BASE for undefined input', () => {
    expect(resolveDirijorApiUrl(undefined)).toBe(DEFAULT_API_BASE);
  });

  it('returns DEFAULT_API_BASE for empty / whitespace-only input', () => {
    expect(resolveDirijorApiUrl('')).toBe(DEFAULT_API_BASE);
    expect(resolveDirijorApiUrl('   ')).toBe(DEFAULT_API_BASE);
  });

  it('strips trailing slashes on a custom base', () => {
    expect(resolveDirijorApiUrl('http://host:8000/')).toBe('http://host:8000');
    expect(resolveDirijorApiUrl('http://host:8000///')).toBe(
      'http://host:8000'
    );
  });

  it('echoes a well-formed custom URL unchanged', () => {
    expect(resolveDirijorApiUrl('http://10.0.0.1:9000')).toBe(
      'http://10.0.0.1:9000'
    );
  });
});

describe('postRealmSpin', () => {
  it('returns the parsed SpinResponse on 202 happy path', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(mockJsonResponse(202, VALID_SPIN_RESPONSE));
    vi.stubGlobal('fetch', fetchMock);

    const result = await postRealmSpin(DEFAULT_API_BASE, {
      realm_description: 'smoke',
    });
    expect(result).toEqual(VALID_SPIN_RESPONSE);
    expect(fetchMock).toHaveBeenCalledWith(
      `${DEFAULT_API_BASE}/realms/spin`,
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
    );
  });

  it('throws SpinApiError on 400 with the backend envelope code preserved', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockJsonResponse(400, {
          code: 'validation_failed',
          message: 'realm_description required',
          details: { field: 'realm_description' },
        })
      )
    );

    await expect(
      postRealmSpin(DEFAULT_API_BASE, { realm_description: '' })
    ).rejects.toMatchObject({
      name: 'SpinApiError',
      code: 'validation_failed',
      httpStatus: 400,
      details: { field: 'realm_description' },
    });
  });

  it('throws SpinApiError with code "realm_id_conflict" on 409', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockJsonResponse(409, {
          code: 'realm_id_conflict',
          message: 'already active',
          details: { existing_job_id: 'abc' },
        })
      )
    );

    await expect(
      postRealmSpin(DEFAULT_API_BASE, {
        realm_description: 'x',
        realm_id: 'dup',
      })
    ).rejects.toMatchObject({
      code: 'realm_id_conflict',
      httpStatus: 409,
    });
  });

  it('throws SpinApiError with code "realm_manager_unavailable" on 503', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockJsonResponse(503, {
          code: 'realm_manager_unavailable',
          message: 'no adapters registered',
          details: {},
        })
      )
    );

    await expect(
      postRealmSpin(DEFAULT_API_BASE, { realm_description: 'x' })
    ).rejects.toMatchObject({
      code: 'realm_manager_unavailable',
      httpStatus: 503,
    });
  });

  it('throws SpinApiError with code "network_error" when fetch rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    );

    const err = await postRealmSpin(DEFAULT_API_BASE, {
      realm_description: 'x',
    }).catch((e) => e);
    expect(err).toBeInstanceOf(SpinApiError);
    expect(err.code).toBe('network_error');
    expect(err.httpStatus).toBe(0);
  });

  it('throws SpinApiError with code "bad_response" when the response body is not valid JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockBadJsonResponse(202)));

    const err = await postRealmSpin(DEFAULT_API_BASE, {
      realm_description: 'x',
    }).catch((e) => e);
    expect(err).toBeInstanceOf(SpinApiError);
    expect(err.code).toBe('bad_response');
    expect(err.httpStatus).toBe(202);
  });

  it('throws SpinApiError "bad_response" when 202 body is missing required keys', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(mockJsonResponse(202, { job_id: 'only-one' }))
    );
    const err = await postRealmSpin(DEFAULT_API_BASE, {
      realm_description: 'x',
    }).catch((e) => e);
    expect(err).toBeInstanceOf(SpinApiError);
    expect(err.code).toBe('bad_response');
  });
});

describe('getRealmJob', () => {
  it('returns the parsed SpinJob on 200 happy path', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(mockJsonResponse(200, VALID_SPIN_JOB))
    );
    const job = await getRealmJob(DEFAULT_API_BASE, VALID_SPIN_JOB.job_id);
    expect(job).toEqual(VALID_SPIN_JOB);
  });

  it('throws SpinApiError with code "job_not_found" on 404', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockJsonResponse(404, {
          code: 'job_not_found',
          message: 'no spin job with id xxx',
          details: { job_id: 'xxx' },
        })
      )
    );
    await expect(getRealmJob(DEFAULT_API_BASE, 'xxx')).rejects.toMatchObject({
      code: 'job_not_found',
      httpStatus: 404,
    });
  });
});

// --- Story 2.2 destroy surface ------------------------------------------------

describe('deleteRealmJob', () => {
  it('returns parsed SpinJob on 202', async () => {
    const job = {
      ...VALID_SPIN_JOB,
      outputs: {
        ...VALID_SPIN_JOB.outputs,
        destroy_requested_at: '2026-04-18T12:00:00.000Z',
        destroyed: false,
      },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(mockJsonResponse(202, job))
    );
    const result = await deleteRealmJob(DEFAULT_API_BASE, job.job_id);
    expect(result).toEqual(job);
  });

  it('returns null on 204', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        status: 204,
        ok: true,
        async json() {
          return {};
        },
      } as unknown as Response)
    );
    expect(await deleteRealmJob(DEFAULT_API_BASE, 'j1')).toBeNull();
  });

  it('throws SpinApiError job_not_found on 404', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockJsonResponse(404, {
          code: 'job_not_found',
          message: 'missing',
          details: { job_id: 'x' },
        })
      )
    );
    await expect(deleteRealmJob(DEFAULT_API_BASE, 'x')).rejects.toMatchObject({
      code: 'job_not_found',
      httpStatus: 404,
    });
  });

  it('throws on 409 destroy_invalid_state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockJsonResponse(409, {
          code: 'destroy_invalid_state',
          message: 'bad phase',
          details: { current_phase: 'provisioning' },
        })
      )
    );
    await expect(deleteRealmJob(DEFAULT_API_BASE, 'j')).rejects.toMatchObject({
      code: 'destroy_invalid_state',
      httpStatus: 409,
    });
  });

  it('throws on 409 destroy_already_requested', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockJsonResponse(409, {
          code: 'destroy_already_requested',
          message: 'already',
          details: { destroy_requested_at: '2026-04-18T12:00:00.000Z' },
        })
      )
    );
    await expect(deleteRealmJob(DEFAULT_API_BASE, 'j')).rejects.toMatchObject({
      code: 'destroy_already_requested',
      httpStatus: 409,
    });
  });

  it('throws network_error when fetch rejects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    const err = await deleteRealmJob(DEFAULT_API_BASE, 'j').catch((e) => e);
    expect(err).toBeInstanceOf(SpinApiError);
    expect(err.code).toBe('network_error');
    expect(err.httpStatus).toBe(0);
  });
});

describe('postMarketplaceImportDraft', () => {
  it('returns parsed success on 200', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockJsonResponse(200, {
          schema_version: 9,
          draft: {
            agent_count: 2,
            realm_description: 'Imported template: t @ 1.0.0',
            adapter_hint: 'local-noop',
            policy_refs: [],
          },
        })
      )
    );
    const res = await postMarketplaceImportDraft(DEFAULT_API_BASE, '{}');
    expect(res.schema_version).toBe(9);
    expect(res.draft.agent_count).toBe(2);
    expect(res.draft.adapter_hint).toBe('local-noop');
  });

  it('throws ImportDraftApiError with Core code on 422', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockJsonResponse(422, {
          schema_version: 9,
          code: 'SCHEMA',
          detail: 'validation failed',
        })
      )
    );
    await expect(
      postMarketplaceImportDraft(DEFAULT_API_BASE, '{}')
    ).rejects.toMatchObject({
      name: 'ImportDraftApiError',
      code: 'SCHEMA',
      httpStatus: 422,
      detail: 'validation failed',
    });
  });

  it('network failures use ImportDraftApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    const err = await postMarketplaceImportDraft(DEFAULT_API_BASE, '{}').catch(
      (e) => e
    );
    expect(err).toBeInstanceOf(ImportDraftApiError);
    expect((err as ImportDraftApiError).code).toBe('network_error');
  });
});

describe('SpinApiError', () => {
  it('exposes a stable .toJSON() surface for logging + error boundaries', () => {
    const err = new SpinApiError('adapter_error', 'boom', 500, {
      exc_type: 'RuntimeError',
    });
    expect(err.toJSON()).toEqual({
      code: 'adapter_error',
      message: 'boom',
      httpStatus: 500,
      details: { exc_type: 'RuntimeError' },
    });
    expect(JSON.parse(JSON.stringify(err))).toEqual(err.toJSON());
  });
});
