import {cleanup, render, screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {RunMetricsPanel} from '../src/features/dashboard/run-metrics-panel';
afterEach(cleanup);
it('separates objective, soft penalty and solver timing with a real bound formula',()=>{
 render(<RunMetricsPanel score={1000} summary={{experiment:{objective_components:{unassigned:0,zero_assigned_lecturers:0,workload_disparity:900,soft_preferences:100},best_objective_bound:900,solver_wall_time_seconds:2.5,model_build_seconds:0.1,solver_pipeline_seconds:3,configuration:{max_time_in_seconds:5,num_search_workers:8,random_seed:1}}}}/>);
 expect(screen.getByText('Tổng objective').nextElementSibling).toHaveTextContent('1.000');
 expect(screen.getByText('Phạt nguyện vọng mềm').nextElementSibling).toHaveTextContent('100');
 expect(screen.getByText(/Gap:/).nextElementSibling).toHaveTextContent('0,1');
 expect(screen.getByText('Solver wall time (giây)').nextElementSibling).toHaveTextContent('2,5');
});
it('never invents objective or solver measurements for manual/legacy snapshots',()=>{
 render(<RunMetricsPanel score={null} summary={{solution_origin:'MANUAL',experiment:null}}/>);
 expect(screen.getByText(/Phiên bản chỉnh thủ công/)).toBeInTheDocument();
 expect(screen.getByText('Tổng objective').nextElementSibling).toHaveTextContent('N/A');
 expect(screen.getByText('Solver wall time (giây)').nextElementSibling).toHaveTextContent('N/A');
});
