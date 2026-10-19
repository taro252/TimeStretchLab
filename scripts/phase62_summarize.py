"""期待台帳に基づく集計。旧資料に台帳がなければINCOMPLETEとして保存。"""
import argparse,json
from phase62_evidence import aggregate

def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('run');parser.add_argument('--output',required=True);a=parser.parse_args()
    result=aggregate(a.run)
    with open(a.output,'x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({k:result.get(k) for k in ('PASS','status','counts','gates','public_go')},ensure_ascii=False))
if __name__=='__main__':main()
