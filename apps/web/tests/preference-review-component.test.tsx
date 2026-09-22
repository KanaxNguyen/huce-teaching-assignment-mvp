import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {PreferenceReview} from '../src/features/dashboard/semester-workflow-app';
import {api} from '../src/services/api';
import type {PreferenceDraft} from '../src/types/api';

const complete={is_confirmable:true,validation_errors:[]};
function draft(id:number,status:PreferenceDraft['status'],raw:string):PreferenceDraft {
  return {id,batch_id:1,draft_kind:'CONSTRAINT',lecturer_id:7,lecturer:'Teacher',lecturer_alias:'Source',
    constraint_type:'UNAVAILABLE',context_type:'TEACHING',context_confidence:'HIGH',context_confirmed:true,
    day_scope:'T2',periods:[1,2,3],start_date:null,end_date:null,hardness:'soft',weight:.8,numeric_value:null,
    target:{},participant_codes:[],seminar_link:null,source_file:'input.xlsx',source_sheet:'Data',source_row:id,source_cell:`C${id}`,
    raw_text:raw,confidence:'HIGH',needs_review:status==='NEEDS_REVIEW',review_reason:null,status,
    rejected_reason:status==='REJECTED'?'Không phù hợp':null,rejected_at:status==='REJECTED'?'2026-09-06':null,
    applied_constraint_id:null,applied_seminar_id:null,is_confirmable:status!=='REJECTED',validation_errors:[]};
}
function props(drafts:PreferenceDraft[]) {
  return {drafts,lecturers:[{id:7,name:'Teacher'}],semesterId:1,busy:'',onSave:vi.fn(),onConfirmHigh:vi.fn(),onApply:vi.fn(),onCreate:vi.fn(async()=>{}),onNext:vi.fn()};
}
beforeEach(()=>{vi.spyOn(api,'validatePreferenceDraft').mockResolvedValue(complete);});
afterEach(()=>{cleanup();vi.restoreAllMocks();});

describe('actual PreferenceReview component',()=>{
  it('reflects confirmation, semantic re-review and counters from canonical server rows',async()=>{
    const row=draft(10,'NEEDS_REVIEW','Stateful source'); const p=props([row]);
    const view=render(<PreferenceReview {...p}/>);
    await waitFor(()=>expect(screen.getByRole('button',{name:/^Xác nhận$/})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:/^Xác nhận$/}));
    expect(p.onSave).toHaveBeenLastCalledWith(row,expect.objectContaining({status:'CONFIRMED'}));
    const confirmed={...row,status:'CONFIRMED' as const,needs_review:false};
    view.rerender(<PreferenceReview {...p} drafts={[confirmed]}/>);
    expect(screen.getByRole('button',{name:'Đã xác nhận (1)'})).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(1);
    fireEvent.change(screen.getByLabelText('Tiết'),{target:{value:'7-9'}});
    await waitFor(()=>expect(screen.getByRole('button',{name:/^Xác nhận$/})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:/^Xác nhận$/}));
    expect(p.onSave).toHaveBeenLastCalledWith(confirmed,expect.objectContaining({periods:[7,8,9]}));
    view.rerender(<PreferenceReview {...p} drafts={[{...confirmed,status:'NEEDS_REVIEW',needs_review:true,periods:[7,8,9]}]}/>);
    expect(screen.getByRole('button',{name:'Cần xác nhận (1)'})).toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Áp dụng đã xác nhận (0)'})).toBeDisabled();
    expect(screen.getAllByRole('article')).toHaveLength(1);
  });

  it('hydrates all relinked rows and removes stale unresolved selection',()=>{
    const rows=[1,2].map(id=>({...draft(id,'NEEDS_REVIEW',`Source ${id}`),lecturer_id:null,lecturer:null}));
    const p=props(rows);const view=render(<PreferenceReview {...p}/>);
    expect(screen.getAllByLabelText('Giảng viên').map(e=>(e as HTMLSelectElement).value)).toEqual(['','']);
    view.rerender(<PreferenceReview {...p} drafts={rows.map(row=>({...row,lecturer_id:7,lecturer:'Teacher'}))}/>);
    expect(screen.getAllByLabelText('Giảng viên').map(e=>(e as HTMLSelectElement).value)).toEqual(['7','7']);
    expect(screen.getAllByRole('article')).toHaveLength(2);
  });
  it('renders rejected badge/reason, filters, counters and restores into active review',()=>{
    const rows=[draft(1,'NEEDS_REVIEW','Review source'),draft(2,'CONFIRMED','Confirmed source'),draft(3,'REJECTED','Rejected source')];
    const p=props(rows);const view=render(<PreferenceReview {...p}/>);
    expect(screen.getByRole('button',{name:'Cần xác nhận (1)'})).toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Đã từ chối (1)'})).toBeInTheDocument();
    const rejected=screen.getByText('Rejected source').closest('article')!;
    expect(within(rejected).getByText('Đã từ chối')).toBeInTheDocument();
    expect(within(rejected).getByText('Không phù hợp')).toBeInTheDocument();
    expect(rejected.className).toContain('preferenceRowRejected');
    fireEvent.click(screen.getByRole('button',{name:'Đã từ chối (1)'}));
    expect(screen.queryByText('Confirmed source')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Khôi phục'}));
    expect(p.onSave).toHaveBeenCalledWith(rows[2],expect.objectContaining({status:'NEEDS_REVIEW',rejected_reason:null}));
    const restored={...rows[2],status:'NEEDS_REVIEW' as const,needs_review:true,rejected_reason:null,rejected_at:null};
    view.rerender(<PreferenceReview {...p} drafts={[rows[0],rows[1],restored]}/>);
    fireEvent.click(screen.getByRole('button',{name:'Cần xác nhận (2)'}));
    expect(screen.getByText('Rejected source')).toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Khôi phục'})).not.toBeInTheDocument();
  });

  it('keeps stable status order under lecturer and excludes rejected from apply action',()=>{
    const rows=[draft(5,'REJECTED','Rejected first'),draft(3,'CONFIRMED','Confirmed first'),draft(2,'DRAFT','Action first'),draft(4,'DRAFT','Action second'),draft(6,'REJECTED','Rejected second')];
    const p=props(rows);render(<PreferenceReview {...p}/>);
    fireEvent.click(screen.getByRole('button',{name:'Theo giảng viên'}));
    fireEvent.change(screen.getByRole('combobox',{name:'Chọn giảng viên'}),{target:{value:'7'}});
    const order=Array.from(document.querySelectorAll('article')).map(a=>a.querySelector('.preferenceCopy p')?.textContent ?? a.querySelector('p')?.textContent);
    expect(order).toEqual(['Action first','Action second','Confirmed first','Rejected first','Rejected second']);
    fireEvent.click(screen.getByRole('button',{name:'Áp dụng đã xác nhận (1)'}));
    expect(p.onApply).toHaveBeenCalledWith([3]);
  });

  it('uses backend validation for incomplete seminar and revalidates edited input without invented periods',async()=>{
    const missing={is_confirmable:false,validation_errors:[{code:'MISSING_PERIOD',field:'periods',message:'Chưa xác định tiết seminar'}]};
    vi.mocked(api.validatePreferenceDraft).mockResolvedValueOnce(missing).mockResolvedValue(complete);
    const row={...draft(1,'NEEDS_REVIEW','SEMINAR: Thứ 2, thời gian chưa xác định'),constraint_type:'SEMINAR_COMMITMENT',context_type:'SEMINAR' as const,periods:[],is_confirmable:false,validation_errors:missing.validation_errors};
    render(<PreferenceReview {...props([row])}/>);
    expect(screen.getByLabelText('Tiết')).toHaveValue('');
    expect(screen.getByRole('button',{name:/^Xác nhận$/})).toBeDisabled();
    await waitFor(()=>expect(api.validatePreferenceDraft).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Chưa xác định tiết seminar')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Tiết'),{target:{value:'4-6'}});
    await waitFor(()=>expect(screen.getByRole('button',{name:/^Xác nhận$/})).toBeEnabled());
    expect(api.validatePreferenceDraft).toHaveBeenLastCalledWith(1,expect.objectContaining({periods:[4,5,6],day_scope:'T2'}),1);
  });
});
